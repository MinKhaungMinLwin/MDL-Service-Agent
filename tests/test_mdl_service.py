"""Focused tests for MDL classification and Neo4j ingestion."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import openpyxl

from mdl_service.classification import MDLClassifier
from mdl_service.loader import extract_titles_from_excel, load_ingest_records
from mdl_service.models import BatchClassification, ClassificationResult, DocumentClassification, MDLIngestConfig
from mdl_service.repository import MDLRepository
from mdl_service.service import MDLClassificationService, MDLIngestService


class MDLServiceTest(unittest.TestCase):
    def test_extracts_titles_and_writes_classified_csv(self) -> None:
        classifier = _FakeClassifier()
        service = MDLClassificationService(classifier, batch_size=1, batch_delay_seconds=0, sleep=lambda _: None)

        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "Sample_MDL.xlsx"
            output_path = Path(directory) / "Sample_MDL_classified.csv"
            workbook = openpyxl.Workbook()
            worksheet = workbook.active
            worksheet.title = "Documents"
            worksheet.append(["Document No.", "Document Description"])
            worksheet.append(["DOC-1", "HVAC GENERAL ARRANGEMENT"])
            workbook.save(input_path)

            titles = extract_titles_from_excel(input_path)
            row_count = service.classify_file(input_path, output_path)
            with open(output_path, newline="", encoding="utf-8-sig") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(titles[0].document_no, "DOC-1")
        self.assertEqual(row_count, 1)
        self.assertEqual(rows[0]["System"], "HVAC")
        self.assertEqual(rows[0]["Deliverable"], "GENERAL ARRANGEMENT")

    def test_loads_normalized_ingest_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "Sample_MDL_classified.csv"
            _write_csv(
                csv_path,
                [
                    {
                        "Source File": "Sample_MDL.xlsx",
                        "Document No": "",
                        "Title": "HVAC GENERAL ARRANGEMENT",
                        "Equipment": "",
                        "Building": "nan",
                        "System": "HVAC",
                        "Study/Survey": "",
                        "Others": "Fresh Air Intake",
                        "Deliverable": "GENERAL ARRANGEMENT",
                    }
                ],
            )
            records = load_ingest_records(csv_path)

        self.assertEqual(records[0]["doc_id"], "Sample_MDL_classified_DOC_0_0")
        self.assertEqual(records[0]["building"], "")
        self.assertEqual(
            records[0]["text_content"],
            "Title: HVAC GENERAL ARRANGEMENT | System: HVAC | Others: Fresh Air Intake | "
            "Deliverable: GENERAL ARRANGEMENT",
        )

    def test_repository_creates_schema_and_upserts_records(self) -> None:
        conn = _RecordingConnection()
        repository = MDLRepository(conn, MDLIngestConfig(embedding_dimensions=3))

        repository.setup_schema()
        repository.upsert_batch([{"doc_id": "doc-1", "embedding": [1.0, 0.0, 0.0]}])

        self.assertIn("CREATE CONSTRAINT test_mdl_doc_id_unique", conn.calls[0][0])
        self.assertIn("CREATE FULLTEXT INDEX test_mdl_document_fulltext_idx", conn.calls[1][0])
        self.assertIn("n.others", conn.calls[1][0])
        self.assertIn("CREATE VECTOR INDEX test_mdl_document_vector_idx", conn.calls[2][0])
        self.assertIn("`vector.dimensions`: 3", conn.calls[2][0])
        self.assertIn("MERGE (n:TestMDLDocument", conn.calls[3][0])
        self.assertIn("n.others = record.others", conn.calls[3][0])
        self.assertEqual(conn.calls[3][1]["batch"][0]["doc_id"], "doc-1")

    def test_ingest_service_embeds_and_upserts_in_batches(self) -> None:
        repository = _RecordingRepository()
        service = MDLIngestService(repository, _EmbeddingService(), MDLIngestConfig(batch_size=2))

        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "Sample_MDL_classified.csv"
            _write_csv(
                csv_path,
                [
                    {"Title": "Doc A"},
                    {"Title": "Doc B"},
                    {"Title": "Doc C"},
                ],
            )
            count = service.ingest_file(csv_path)

        self.assertEqual(count, 3)
        self.assertEqual([len(batch) for batch in repository.batches], [2, 1])
        self.assertEqual(repository.batches[0][0]["embedding"], [1.0, 0.0])

    def test_classifier_preserves_prompt_and_pads_short_response(self) -> None:
        client = _StructuredOutputClient(
            BatchClassification(
                results=[
                    DocumentClassification(
                        equipment="",
                        building="",
                        system=" HVAC ",
                        study_survey="",
                        others="",
                        deliverable=" General Arrangement ",
                    )
                ]
            )
        )
        classifier = MDLClassifier(client, "deployment", "SYSTEM PROMPT", sleep=lambda _: None)

        results = classifier.classify_titles(["Doc A", "Doc B"])

        self.assertEqual(client.parameters["messages"][0]["content"], "SYSTEM PROMPT")
        self.assertEqual(results[0].system, "HVAC")
        self.assertEqual(results[1].note, "missing from batch response")


class _FakeClassifier:
    def classify_titles(self, titles: list[str]) -> list[ClassificationResult]:
        return [ClassificationResult(system="HVAC", deliverable="GENERAL ARRANGEMENT") for _ in titles]


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def session(self):
        return _RecordingSession(self.calls)


class _RecordingSession:
    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def run(self, query: str, **parameters) -> None:
        self.calls.append((query, parameters))


class _RecordingRepository:
    def __init__(self) -> None:
        self.batches: list[list[dict]] = []

    def upsert_batch(self, records: list[dict]) -> None:
        self.batches.append(records)


class _EmbeddingService:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class _StructuredOutputClient:
    def __init__(self, parsed: BatchClassification) -> None:
        self.parameters = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))
        self.parsed = parsed

    def _parse(self, **parameters):
        self.parameters = parameters
        message = SimpleNamespace(parsed=self.parsed)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "Source File",
        "Document No",
        "Title",
        "Equipment",
        "Building",
        "System",
        "Study/Survey",
        "Others",
        "Deliverable",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
