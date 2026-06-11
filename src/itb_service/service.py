"""Application service for ITB depth and keyword extraction."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from loguru import logger

from itb_service.extraction import as_text, extract_chunk_batch, failed_extraction
from itb_service.loader import load_target_chunks, prepare_chunks
from itb_service.models import ITBExtractionConfig, ITBTarget, PreparedChunk
from itb_service.output import (
    build_csv_row,
    build_rejected_csv_row,
    build_token_row,
    read_csv_rows,
    write_outputs,
    write_rejected_outputs,
)
from itb_service.verification import build_verification_payload, failed_verification, verify_extraction_batch


class ITBExtractionService:
    """Extract depth metadata from parsed ITB chunks and optionally verify it."""

    def __init__(
        self,
        client: Any,
        config: ITBExtractionConfig,
        extraction_prompt: str,
        abbreviation_rules: dict[str, str],
        verification_prompt: str = "",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if config.enable_verification and not verification_prompt:
            raise ValueError("verification_prompt is required when verification is enabled")
        self.client = client
        self.config = config
        self.extraction_prompt = extraction_prompt
        self.verification_prompt = verification_prompt
        self.abbreviation_rules = abbreviation_rules
        self.sleep = sleep

    def extract_to_files(
        self,
        targets: list[ITBTarget],
        csv_path: str | Path,
        token_path: str | Path,
        rejected_csv_path: str | Path | None = None,
    ) -> int:
        """Extract configured targets and write CSV and token artifacts."""
        csv_rows = read_csv_rows(csv_path)
        token_rows = read_csv_rows(token_path)
        rejected_csv_rows = read_csv_rows(rejected_csv_path) if rejected_csv_path else []
        completed_chunk_ids = _csv_chunk_ids(csv_rows) | _csv_chunk_ids(rejected_csv_rows)
        if completed_chunk_ids:
            logger.info("Resuming ITB extraction with {} completed chunk(s)", len(completed_chunk_ids))
        extracted_count = 0
        order_by_chunk_id: dict[str, int] = {}
        order_by_document: dict[str, int] = {}
        for target in targets:
            order_by_document.setdefault(target.document_name, len(order_by_document))
            chunks = load_target_chunks(target, self.config.max_chunks)
            for chunk in chunks:
                chunk_id = as_text(chunk.get("chunk_id"))
                if chunk_id and chunk_id not in order_by_chunk_id:
                    order_by_chunk_id[chunk_id] = len(order_by_chunk_id)
            prepared_chunks = prepare_chunks(
                target.document_name,
                chunks,
                self.abbreviation_rules,
                self.config.requested_section,
            )
            skipped_count = sum(
                1 for item in prepared_chunks if as_text(item.chunk.get("chunk_id")) in completed_chunk_ids
            )
            prepared_chunks = [
                item for item in prepared_chunks if as_text(item.chunk.get("chunk_id")) not in completed_chunk_ids
            ]
            logger.info(
                "{}: loaded {} target chunks, skipped {} completed chunks, and prepared {} remaining chunks",
                target.document_name,
                len(chunks),
                skipped_count,
                len(prepared_chunks),
            )
            batches = _chunked(prepared_chunks, self.config.batch_size)
            indexed_batches = list(enumerate(batches, start=1))
            if self.config.max_concurrency > 1 and indexed_batches:
                logger.info(
                    "{}: processing {} batch(es) with concurrency {}",
                    target.document_name,
                    len(indexed_batches),
                    self.config.max_concurrency,
                )
            for batch_index, batch_result in self._run_batches(target.document_name, indexed_batches):
                (
                    batch_csv_rows,
                    batch_token_rows,
                    batch_rejected_csv_rows,
                ) = batch_result
                csv_rows.extend(batch_csv_rows)
                token_rows.extend(batch_token_rows)
                rejected_csv_rows.extend(batch_rejected_csv_rows)
                completed_chunk_ids.update(_csv_chunk_ids(batch_csv_rows))
                completed_chunk_ids.update(_csv_chunk_ids(batch_rejected_csv_rows))
                extracted_count += len(batch_csv_rows)
                csv_rows = _sort_csv_rows(csv_rows, order_by_chunk_id)
                token_rows = _sort_token_rows(token_rows, order_by_document)
                rejected_csv_rows = _sort_csv_rows(rejected_csv_rows, order_by_chunk_id)
                write_outputs(csv_path, token_path, csv_rows, token_rows)
                if rejected_csv_path:
                    write_rejected_outputs(
                        rejected_csv_path,
                        rejected_csv_rows,
                    )
                logger.info("{}: completed batch {}/{}", target.document_name, batch_index, len(batches))
                self.sleep(self.config.batch_delay_seconds)
        csv_rows = _sort_csv_rows(csv_rows, order_by_chunk_id)
        token_rows = _sort_token_rows(token_rows, order_by_document)
        rejected_csv_rows = _sort_csv_rows(rejected_csv_rows, order_by_chunk_id)
        write_outputs(csv_path, token_path, csv_rows, token_rows)
        if rejected_csv_path:
            write_rejected_outputs(rejected_csv_path, rejected_csv_rows)
            logger.info("Rejected {} chunk(s) outside requested section", len(rejected_csv_rows))
        return extracted_count

    def _run_batches(
        self,
        document_name: str,
        indexed_batches: list[tuple[int, list[PreparedChunk]]],
    ):
        if self.config.max_concurrency == 1:
            for batch_index, batch in indexed_batches:
                yield batch_index, self._run_indexed_batch(document_name, batch_index, len(indexed_batches), batch)
            return
        with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as executor:
            futures = {
                executor.submit(
                    self._run_indexed_batch,
                    document_name,
                    batch_index,
                    len(indexed_batches),
                    batch,
                ): batch_index
                for batch_index, batch in indexed_batches
            }
            for future in as_completed(futures):
                yield futures[future], future.result()

    def _run_indexed_batch(
        self,
        document_name: str,
        batch_index: int,
        batch_count: int,
        batch: list[PreparedChunk],
    ) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
        logger.info(
            "{}: processing batch {}/{} ({} chunk{})",
            document_name,
            batch_index,
            batch_count,
            len(batch),
            "" if len(batch) == 1 else "s",
        )
        return self._extract_batch(document_name, batch_index, batch)

    def _extract_batch(
        self,
        document_name: str,
        batch_index: int,
        batch: list[PreparedChunk],
    ) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
        payloads = [item.payload for item in batch]
        batch_error = ""
        try:
            logger.info("Running ITB extraction for {} chunk{}", len(batch), "" if len(batch) == 1 else "s")
            results_by_id, batch_token_usage = extract_chunk_batch(
                self.client,
                self.config.model,
                self.extraction_prompt,
                payloads,
            )
        except Exception as exc:
            logger.exception("ITB extraction batch failed")
            results_by_id = {}
            batch_token_usage = {}
            batch_error = str(exc)

        extraction_by_id, error_by_id = self._resolve_extractions(batch, results_by_id, batch_error)
        verification_by_id = self._verify_batch(document_name, batch, extraction_by_id, error_by_id)
        csv_rows = []
        token_rows = []
        rejected_csv_rows = []
        token_rows.append(
            build_token_row(document_name, batch_index, [item.chunk for item in batch], batch_token_usage)
        )
        for item in batch:
            chunk_id = as_text(item.chunk.get("chunk_id"))
            extraction = extraction_by_id[chunk_id]
            if self._is_rejected_by_section_boundary(extraction):
                logger.info(
                    "{}: rejected chunk {} outside requested section {}",
                    document_name,
                    chunk_id,
                    self.config.requested_section,
                )
                rejected_csv_rows.append(
                    build_rejected_csv_row(document_name, item.chunk, extraction, self.config.requested_section)
                )
                continue
            verification = verification_by_id.get(chunk_id, {})
            csv_rows.append(build_csv_row(document_name, item.chunk, item.hierarchy, extraction, verification))
        return csv_rows, token_rows, rejected_csv_rows

    def _resolve_extractions(
        self,
        batch: list[PreparedChunk],
        results_by_id: dict[str, dict[str, Any]],
        batch_error: str,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        extractions = {}
        errors = {}
        for item in batch:
            chunk_id = as_text(item.chunk.get("chunk_id"))
            error = batch_error
            extraction = results_by_id.get(chunk_id)
            if extraction is None:
                error = error or f"Missing model result for chunk_id: {chunk_id}"
                extraction = failed_extraction(error)
            extractions[chunk_id] = extraction
            if error:
                errors[chunk_id] = error
        return extractions, errors

    def _verify_batch(
        self,
        document_name: str,
        batch: list[PreparedChunk],
        extraction_by_id: dict[str, dict[str, Any]],
        error_by_id: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        if not self.config.enable_verification:
            return {}
        payloads = [
            build_verification_payload(
                document_name,
                item.chunk,
                item.hierarchy,
                item.known_abbreviations,
                extraction_by_id[chunk_id],
            )
            for item in batch
            if (
                (chunk_id := as_text(item.chunk.get("chunk_id"))) not in error_by_id
                and not self._is_rejected_by_section_boundary(extraction_by_id[chunk_id])
            )
        ]
        if not payloads:
            return {}
        try:
            logger.info("Running ITB verification for {} chunk{}", len(payloads), "" if len(payloads) == 1 else "s")
            results_by_id = verify_extraction_batch(self.client, self.config.model, self.verification_prompt, payloads)
            return {
                chunk_id: results_by_id.get(
                    chunk_id,
                    failed_verification(f"Missing model verification result for chunk_id: {chunk_id}"),
                )
                for payload in payloads
                if (chunk_id := as_text(payload.get("chunk_id")))
            }
        except Exception as exc:
            logger.exception("ITB verification batch failed")
            return {as_text(payload.get("chunk_id")): failed_verification(exc) for payload in payloads}

    def _is_rejected_by_section_boundary(self, extraction: dict[str, Any]) -> bool:
        if not self.config.requested_section:
            return False
        value = extraction.get("belongs_to_requested_section")
        if isinstance(value, bool):
            return not value
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"false", "no", "n", "0"}:
                return True
            if normalized in {"true", "yes", "y", "1"}:
                return False
        return False


def _chunked(items: list[PreparedChunk], size: int) -> list[list[PreparedChunk]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _csv_chunk_ids(rows: list[list[Any]]) -> set[str]:
    return {chunk_id for row in rows if len(row) > 1 and (chunk_id := as_text(row[1]))}


def _sort_csv_rows(rows: list[list[Any]], order_by_chunk_id: dict[str, int]) -> list[list[Any]]:
    return sorted(rows, key=lambda row: _row_order(row[1] if len(row) > 1 else "", order_by_chunk_id))


def _sort_token_rows(rows: list[list[Any]], order_by_document: dict[str, int]) -> list[list[Any]]:
    return sorted(rows, key=lambda row: (_row_order(row[0] if row else "", order_by_document), _batch_order(row)))


def _batch_order(row: list[Any]) -> int:
    if len(row) <= 1:
        return 0
    try:
        return int(row[1])
    except (TypeError, ValueError):
        return 0


def _row_order(value: Any, order_by_value: dict[str, int]) -> int:
    return order_by_value.get(as_text(value), len(order_by_value))
