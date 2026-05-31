"""Application service for ITB depth and keyword extraction."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from itb_service.extraction import as_text, extract_chunk_batch, failed_extraction, split_token_usage
from itb_service.loader import load_target_chunks, prepare_chunks
from itb_service.models import ITBExtractionConfig, ITBTarget, PreparedChunk
from itb_service.output import build_csv_row, build_json_record, build_token_row, write_outputs
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
        json_path: str | Path,
        token_path: str | Path,
    ) -> int:
        """Extract configured targets and write CSV, JSON, and token artifacts."""
        csv_rows = []
        json_records = []
        token_rows = []
        for target in targets:
            chunks = load_target_chunks(target, self.config.max_chunks)
            prepared_chunks = prepare_chunks(target.document_name, chunks, self.abbreviation_rules)
            logger.info(
                "{}: loaded {} target chunks and prepared {} non-empty chunks",
                target.document_name,
                len(chunks),
                len(prepared_chunks),
            )
            for batch in _chunked(prepared_chunks, self.config.batch_size):
                batch_csv_rows, batch_json_records, batch_token_rows = self._extract_batch(target.document_name, batch)
                csv_rows.extend(batch_csv_rows)
                json_records.extend(batch_json_records)
                token_rows.extend(batch_token_rows)
                self.sleep(self.config.batch_delay_seconds)
        write_outputs(csv_path, json_path, token_path, csv_rows, json_records, token_rows)
        return len(csv_rows)

    def _extract_batch(
        self,
        document_name: str,
        batch: list[PreparedChunk],
    ) -> tuple[list[list[Any]], list[dict[str, Any]], list[list[Any]]]:
        payloads = [item.payload for item in batch]
        batch_error = ""
        try:
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

        per_chunk_usage = split_token_usage(batch_token_usage, len(batch))
        extraction_by_id, error_by_id = self._resolve_extractions(batch, results_by_id, batch_error)
        verification_by_id = self._verify_batch(document_name, batch, extraction_by_id, error_by_id)
        csv_rows = []
        json_records = []
        token_rows = []
        for item in batch:
            chunk_id = as_text(item.chunk.get("chunk_id"))
            extraction = extraction_by_id[chunk_id]
            verification = verification_by_id.get(chunk_id, {})
            csv_rows.append(build_csv_row(document_name, item.chunk, item.hierarchy, extraction, verification))
            json_records.append(
                build_json_record(
                    document_name,
                    item.chunk,
                    item.hierarchy,
                    extraction,
                    per_chunk_usage,
                    item.known_abbreviations,
                    verification=verification,
                    error=error_by_id.get(chunk_id, ""),
                )
            )
            token_rows.append(build_token_row(document_name, item.chunk, per_chunk_usage))
        return csv_rows, json_records, token_rows

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
            build_verification_payload(document_name, item.chunk, item.hierarchy, extraction_by_id[chunk_id])
            for item in batch
            if (chunk_id := as_text(item.chunk.get("chunk_id"))) not in error_by_id
        ]
        if not payloads:
            return {}
        try:
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


def _chunked(items: list[PreparedChunk], size: int) -> list[list[PreparedChunk]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
