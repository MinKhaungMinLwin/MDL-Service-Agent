"""Application service for ACC-related MDL catalog filtering."""

from __future__ import annotations

import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from loguru import logger

from mdl_service.acc_filter import filter_acc_batch
from mdl_service.output import write_acc_filter_outputs


class ACCFilterService:
    """Filter MDL catalog rows with an LLM, writing resumable outputs."""

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
        """Filter one exported MDL catalog CSV."""
        return self.filter_rows(_read_dict_rows(input_path), output_dir)

    def filter_rows(self, rows: list[dict[str, Any]], output_dir: str | Path) -> int:
        """Filter in-memory MDL catalog rows."""
        completed_rows = _read_dict_rows(Path(output_dir) / "acc_mdl_catalog.csv")
        completed_doc_ids = {_clean(row.get("Doc ID")) for row in completed_rows if _clean(row.get("Doc ID"))}
        order_by_doc_id = {_clean(row.get("Doc ID")): index for index, row in enumerate(rows)}
        remaining_rows = [row for row in rows if _clean(row.get("Doc ID")) not in completed_doc_ids]
        logger.info(
            "Loaded {} MDL rows, skipped {} completed rows, and prepared {} remaining rows",
            len(rows),
            len(completed_doc_ids),
            len(remaining_rows),
        )
        batches = list(enumerate(_chunked(remaining_rows, self.batch_size), start=1))
        all_rows = completed_rows
        try:
            for batch_index, batch_rows in self._run_batches(batches):
                all_rows.extend(batch_rows)
                all_rows = _sort_rows(all_rows, order_by_doc_id)
                write_acc_filter_outputs(output_dir, all_rows)
                logger.info("Completed ACC filter batch {}/{}", batch_index, len(batches))
        except KeyboardInterrupt:
            all_rows = _sort_rows(all_rows, order_by_doc_id)
            write_acc_filter_outputs(output_dir, all_rows)
            logger.warning("Stopped by user. Saved {} ACC filter rows to {}", len(all_rows), output_dir)
            return len(all_rows)
        write_acc_filter_outputs(output_dir, _sort_rows(all_rows, order_by_doc_id))
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
                    "Running ACC filter batch {}/{} ({} docs, attempt {}/{})",
                    batch_index,
                    batch_count,
                    len(rows),
                    attempt,
                    3,
                )
                judgments = filter_acc_batch(self.client, self.model, self.system_prompt, rows)
                return [_merge_judgment(row, judgments.get(_clean(row.get("Doc ID")), {})) for row in rows]
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "ACC filter batch {}/{} failed on attempt {}: {}",
                    batch_index,
                    batch_count,
                    attempt,
                    exc,
                )
                time.sleep(2.0 * attempt)
        if last_error is not None:
            raise last_error
        return []


def _merge_judgment(row: dict[str, Any], judgment: dict[str, Any]) -> dict[str, Any]:
    is_acc_related = judgment.get("is_acc_related")
    value = str(is_acc_related) if isinstance(is_acc_related, bool) else _clean(is_acc_related) or "False"
    return {
        **row,
        "Is ACC Related": value,
    }


def _read_dict_rows(path: str | Path) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def _chunked(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _sort_rows(rows: list[dict[str, Any]], order_by_doc_id: dict[str, int]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: order_by_doc_id.get(_clean(row.get("Doc ID")), len(order_by_doc_id)))


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
