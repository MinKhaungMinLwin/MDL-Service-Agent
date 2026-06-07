"""Application service for ACC-related ITB chunk filtering."""

from __future__ import annotations

import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from loguru import logger

from itb_service.acc_filter import filter_itb_acc_batch
from itb_service.models import ACC_CHUNK_FILTER_FIELDNAMES


class ITBACCFilterService:
    """Filter ITB extraction rows with an LLM, writing resumable CSV outputs."""

    def __init__(
        self,
        client: Any,
        model: str,
        system_prompt: str,
        batch_size: int = 10,
        max_concurrency: int = 1,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.batch_size = batch_size
        self.max_concurrency = max_concurrency

    def filter_file(self, input_path: str | Path, output_dir: str | Path) -> int:
        """Filter one ITB extraction CSV."""
        rows = _read_dict_rows(input_path)
        completed_rows = _read_dict_rows(Path(output_dir) / "itb_acc_filter_judgments.csv")
        completed_chunk_ids = {_clean(row.get("Chunk ID")) for row in completed_rows if _clean(row.get("Chunk ID"))}
        order_by_chunk_id = {_clean(row.get("Chunk ID")): index for index, row in enumerate(rows)}
        remaining_rows = [row for row in rows if _clean(row.get("Chunk ID")) not in completed_chunk_ids]
        logger.info(
            "Loaded {} ITB rows, skipped {} completed rows, and prepared {} remaining rows",
            len(rows),
            len(completed_chunk_ids),
            len(remaining_rows),
        )
        batches = list(enumerate(_chunked(remaining_rows, self.batch_size), start=1))
        all_rows = completed_rows
        try:
            for batch_index, batch_rows in self._run_batches(batches):
                all_rows.extend(batch_rows)
                all_rows = _sort_rows(all_rows, order_by_chunk_id)
                write_itb_acc_filter_outputs(output_dir, all_rows)
                logger.info("Completed ITB ACC filter batch {}/{}", batch_index, len(batches))
        except KeyboardInterrupt:
            all_rows = _sort_rows(all_rows, order_by_chunk_id)
            write_itb_acc_filter_outputs(output_dir, all_rows)
            logger.warning("Stopped by user. Saved {} ITB ACC filter rows to {}", len(all_rows), output_dir)
            return len(all_rows)
        write_itb_acc_filter_outputs(output_dir, _sort_rows(all_rows, order_by_chunk_id))
        return len(all_rows)

    def _run_batches(self, batches: list[tuple[int, list[dict[str, Any]]]]):
        if self.max_concurrency == 1:
            for batch_index, batch in batches:
                yield batch_index, self._run_batch(batch_index, len(batches), batch)
            return
        executor = ThreadPoolExecutor(max_workers=self.max_concurrency)
        try:
            futures = {
                executor.submit(self._run_batch, batch_index, len(batches), batch): batch_index
                for batch_index, batch in batches
            }
            for future in as_completed(futures):
                yield futures[future], future.result()
        except KeyboardInterrupt:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown()

    def _run_batch(
        self,
        batch_index: int,
        batch_count: int,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                logger.info(
                    "Running ITB ACC filter batch {}/{} ({} chunks, attempt {}/{})",
                    batch_index,
                    batch_count,
                    len(rows),
                    attempt,
                    3,
                )
                judgments = filter_itb_acc_batch(self.client, self.model, self.system_prompt, rows)
                return [_merge_judgment(row, judgments.get(_clean(row.get("Chunk ID")), {})) for row in rows]
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "ITB ACC filter batch {}/{} failed on attempt {}: {}",
                    batch_index,
                    batch_count,
                    attempt,
                    exc,
                )
                time.sleep(2.0 * attempt)
        if last_error is not None:
            raise last_error
        return []


def write_itb_acc_filter_outputs(output_dir: str | Path, rows: list[dict[str, Any]]) -> None:
    """Write all ITB ACC filter judgments and the positive ACC-only chunks."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    positive_rows = [row for row in rows if _is_true(row.get("Is ACC Related"))]
    _write_dict_csv(directory / "itb_acc_filter_judgments.csv", ACC_CHUNK_FILTER_FIELDNAMES, rows)
    _write_dict_csv(directory / "itb_acc_chunks.csv", ACC_CHUNK_FILTER_FIELDNAMES, positive_rows)


def _merge_judgment(row: dict[str, Any], judgment: dict[str, Any]) -> dict[str, Any]:
    is_acc_related = judgment.get("is_acc_related")
    value = str(is_acc_related) if isinstance(is_acc_related, bool) else _clean(is_acc_related) or "False"
    return {
        **row,
        "Is ACC Related": value,
        "ACC Reason": _clean(judgment.get("reason")),
    }


def _read_dict_rows(path: str | Path) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def _write_dict_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    last_error: OSError | None = None
    for attempt in range(1, 6):
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5 * attempt)
    if last_error is not None:
        raise last_error


def _chunked(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _sort_rows(rows: list[dict[str, Any]], order_by_chunk_id: dict[str, int]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: order_by_chunk_id.get(_clean(row.get("Chunk ID")), len(order_by_chunk_id)))


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "yes", "y", "1"}


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
