"""Application services for MDL classification and ingestion."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from loguru import logger

from mdl_service.classification import MDLClassifier
from mdl_service.loader import dedupe_ingest_records, extract_titles_from_excel, load_ingest_records
from mdl_service.models import DocumentTitle
from mdl_service.models import MDLIngestConfig
from mdl_service.output import write_classified_csv
from mdl_service.repository import MDLRepository


class MDLClassificationService:
    """Classify MDL titles from Excel and write a downstream-compatible CSV."""

    def __init__(
        self,
        classifier: MDLClassifier,
        batch_size: int = 20,
        max_concurrency: int = 1,
        batch_delay_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if batch_delay_seconds < 0:
            raise ValueError("batch_delay_seconds cannot be negative")
        self.classifier = classifier
        self.batch_size = batch_size
        self.max_concurrency = max_concurrency
        self.batch_delay_seconds = batch_delay_seconds
        self.sleep = sleep

    def classify_file(self, input_path: str | Path, output_path: str | Path) -> int:
        """Classify all titles from one MDL workbook."""
        titles = extract_titles_from_excel(input_path)
        logger.info("Extracted {} MDL titles from {}", len(titles), input_path)
        rows = self.classify_titles(titles)
        if rows:
            write_classified_csv(output_path, rows)
        return len(rows)

    def classify_titles(self, titles: list[DocumentTitle]) -> list[dict[str, str]]:
        """Classify in-memory MDL titles and return downstream-compatible CSV rows."""
        batches = list(enumerate(_chunked(titles, self.batch_size), start=1))
        if self.max_concurrency > 1 and batches:
            logger.info(
                "Classifying {} batch(es) with concurrency {}",
                len(batches),
                self.max_concurrency,
            )
        indexed_rows = []
        for batch_index, batch_rows in self._run_batches(batches):
            indexed_rows.append((batch_index, batch_rows))
            logger.info("Completed MDL classification batch {}/{}", batch_index, len(batches))
            if self.batch_delay_seconds and batch_index < len(batches):
                self.sleep(self.batch_delay_seconds)
        rows = [
            row
            for _, batch_rows in sorted(indexed_rows, key=lambda item: item[0])
            for row in batch_rows
        ]
        return rows

    def _run_batches(self, batches: list[tuple[int, list[Any]]]):
        if self.max_concurrency == 1:
            for batch_index, batch in batches:
                yield batch_index, self._run_batch(batch_index, len(batches), batch)
            return
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
            futures = {
                executor.submit(self._run_batch, batch_index, len(batches), batch): batch_index
                for batch_index, batch in batches
            }
            for future in as_completed(futures):
                yield futures[future], future.result()

    def _run_batch(
        self,
        batch_index: int,
        batch_count: int,
        batch: list[Any],
    ) -> list[dict[str, str]]:
        logger.info(
            "Running MDL classification batch {}/{} ({} title{})",
            batch_index,
            batch_count,
            len(batch),
            "" if len(batch) == 1 else "s",
        )
        results = self.classifier.classify_titles([item.title for item in batch])
        return [item.to_csv_row(result) for item, result in zip(batch, results, strict=True)]


class MDLIngestService:
    """Embed classified MDL documents and upsert them into Neo4j."""

    def __init__(
        self,
        repository: MDLRepository,
        embedding_service: Any,
        config: MDLIngestConfig,
    ) -> None:
        self.repository = repository
        self.embedding_service = embedding_service
        self.config = config

    def setup(self) -> None:
        """Create the schema required for MDL ingestion and matching."""
        self.repository.setup_schema()

    def ingest_directory(self, directory: str | Path) -> int:
        """Ingest every classified MDL CSV in a directory."""
        paths = sorted(Path(directory).glob("*_classified.csv"))
        records = []
        for path in paths:
            records.extend(load_ingest_records(path))
        deduped_records = dedupe_ingest_records(records)
        logger.info(
            "Ingesting {} deduplicated MDL documents from {} classified file(s)",
            len(deduped_records),
            len(paths),
        )
        return self._ingest_records(deduped_records)

    def ingest_file(self, csv_path: str | Path) -> int:
        """Embed and upsert every classified MDL document in one CSV."""
        records = load_ingest_records(csv_path)
        logger.info("Ingesting {} MDL documents from {}", len(records), csv_path)
        return self._ingest_records(records)

    def _ingest_records(self, records: list[dict[str, Any]]) -> int:
        """Embed and upsert prepared MDL records."""
        for start in range(0, len(records), self.config.batch_size):
            batch = records[start : start + self.config.batch_size]
            embeddings = self._embed_texts([record["text_content"] for record in batch])
            if len(embeddings) != len(batch):
                raise ValueError("Embedding service returned an unexpected number of embeddings")
            for record, embedding in zip(batch, embeddings, strict=True):
                record["embedding"] = embedding
            self.repository.upsert_batch(batch)
        return len(records)

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if hasattr(self.embedding_service, "embed_texts"):
            return self.embedding_service.embed_texts(texts)
        return self.embedding_service.embed_batch(texts)


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
