"""Focused tests for MDL classification and Neo4j ingestion."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import openpyxl

from mdl_service.acc_filter import parse_acc_filter_results
from mdl_service.acc_filter_service import ACCFilterService
from mdl_service.classification import MDLClassifier
from mdl_service.cli import _build_catalog_row
from mdl_service.loader import extract_titles_from_excel, load_ingest_records
from mdl_service.models import BatchClassification, ClassificationResult, DocumentClassification, MDLIngestConfig
from mdl_service.output import write_catalog_outputs
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
        self.assertIn("Title: HVAC GENERAL ARRANGEMENT", records[0]["text_content"])
        self.assertIn("Expanded Terms:", records[0]["text_content"])
        self.assertIn("Heating Ventilating and Air Conditioning", records[0]["text_content"])

    def test_repository_creates_schema_and_upserts_records(self) -> None:
        conn = _RecordingConnection()
        repository = MDLRepository(conn, MDLIngestConfig(embedding_dimensions=3))

        repository.setup_schema()
        repository.upsert_batch([{"doc_id": "doc-1", "embedding": [1.0, 0.0, 0.0]}])

        self.assertIn("CREATE CONSTRAINT test_mdl_doc_id_unique", conn.calls[0][0])
        self.assertIn("SHOW INDEXES", conn.calls[1][0])
        self.assertIn("CREATE FULLTEXT INDEX test_mdl_document_fulltext_idx", conn.calls[2][0])
        self.assertIn("n.others", conn.calls[2][0])
        self.assertIn("CREATE VECTOR INDEX test_mdl_document_vector_idx", conn.calls[3][0])
        self.assertIn("`vector.dimensions`: 3", conn.calls[3][0])
        self.assertIn("MERGE (n:TestMDLDocument", conn.calls[4][0])
        self.assertIn("n.others = record.others", conn.calls[4][0])
        self.assertEqual(conn.calls[4][1]["batch"][0]["doc_id"], "doc-1")

    def test_repository_recreates_stale_fulltext_index(self) -> None:
        conn = _RecordingConnection(index_properties=["title", "text_content"])
        repository = MDLRepository(conn, MDLIngestConfig())

        repository.setup_schema()

        self.assertIn("DROP INDEX test_mdl_document_fulltext_idx", conn.calls[2][0])
        self.assertIn("CREATE FULLTEXT INDEX test_mdl_document_fulltext_idx", conn.calls[3][0])

    def test_repository_exports_catalog_by_project_terms(self) -> None:
        conn = _RecordingConnection(records=[{"source_file": "Fadhili_MDL.xlsx", "title": "ACC Layout"}])
        repository = MDLRepository(conn, MDLIngestConfig())

        records = repository.export_catalog(["Fadhili", "R&N"], limit=10)

        self.assertEqual(records[0]["title"], "ACC Layout")
        self.assertIn("MATCH (n:TestMDLDocument)", conn.calls[0][0])
        self.assertEqual(conn.calls[0][1]["project_terms"], ["Fadhili", "R&N"])
        self.assertEqual(conn.calls[0][1]["limit"], 10)

    def test_writes_catalog_outputs(self) -> None:
        row = _build_catalog_row(
            {
                "doc_id": "doc-1",
                "source_file": "Turkistan_MDL.xlsx",
                "document_no": "T-001",
                "title": "Air Cooled Condenser Datasheet",
            },
            ["Fadhili", "R&N", "Turkistan"],
        )

        with tempfile.TemporaryDirectory() as directory:
            write_catalog_outputs(directory, [row], stem="sample_catalog")
            csv_path = Path(directory) / "sample_catalog.csv"
            json_path = Path(directory) / "sample_catalog.json"
            with open(csv_path, newline="", encoding="utf-8-sig") as file:
                rows = list(csv.DictReader(file))

            self.assertTrue(json_path.exists())
            self.assertEqual(rows[0]["Project Name"], "Turkistan")
            self.assertEqual(rows[0]["Title"], "Air Cooled Condenser Datasheet")

    def test_parses_acc_filter_results_by_doc_id(self) -> None:
        results = parse_acc_filter_results(
            {
                "results": [
                    {"doc_id": "doc-1", "is_acc_related": True},
                    {"doc_id": "", "is_acc_related": False},
                ]
            }
        )

        self.assertEqual(results["doc-1"]["is_acc_related"], True)
        self.assertNotIn("", results)

    def test_acc_filter_service_writes_resumable_outputs(self) -> None:
        client = _ChatCompletionClient(
            {
                "results": [
                    {
                        "doc_id": "doc-1",
                        "is_acc_related": True,
                    },
                    {
                        "doc_id": "doc-2",
                        "is_acc_related": False,
                    },
                ]
            }
        )
        service = ACCFilterService(client, "deployment", "SYSTEM", batch_size=2)

        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "catalog.csv"
            _write_catalog_csv(
                input_path,
                [
                    {"Doc ID": "doc-1", "Title": "ACC Layout"},
                    {"Doc ID": "doc-2", "Title": "Cooling Water Pump"},
                ],
            )
            count = service.filter_file(input_path, Path(directory) / "out")
            with open(Path(directory) / "out" / "acc_mdl_catalog.csv", newline="", encoding="utf-8-sig") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(count, 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Doc ID"], "doc-1")

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
                        equipment=" ACC ",
                        building="",
                        system=" HVAC ",
                        study_survey="",
                        others="",
                        deliverable=" P&ID ",
                    )
                ]
            )
        )
        classifier = MDLClassifier(client, "deployment", "SYSTEM PROMPT", sleep=lambda _: None)

        results = classifier.classify_titles(["ACC HVAC P&ID", "Doc B"])

        self.assertEqual(client.parameters["messages"][0]["content"], "SYSTEM PROMPT")
        self.assertIn(
            'Abbreviation Hints = "HVAC = Heating Ventilating and Air Conditioning; P&ID = Piping and Instrumentation Diagram; ACC = Air Cooled Condenser"',
            client.parameters["messages"][1]["content"],
        )
        self.assertEqual(results[0].equipment, "ACC | Air Cooled Condenser")
        self.assertEqual(results[0].system, "HVAC | Heating Ventilating and Air Conditioning")
        self.assertEqual(results[0].deliverable, "P&ID | Piping and Instrumentation Diagram")
        self.assertEqual(results[1].note, "missing from batch response")


class _FakeClassifier:
    def classify_titles(self, titles: list[str]) -> list[ClassificationResult]:
        return [ClassificationResult(system="HVAC", deliverable="GENERAL ARRANGEMENT") for _ in titles]


class _RecordingConnection:
    def __init__(self, index_properties: list[str] | None = None, records: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.index_properties = index_properties
        self.records = records or []

    def session(self):
        return _RecordingSession(self.calls, self.index_properties, self.records)


class _RecordingSession:
    def __init__(self, calls: list[tuple[str, dict]], index_properties: list[str] | None, records: list[dict]) -> None:
        self.calls = calls
        self.index_properties = index_properties
        self.records = records

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def run(self, query: str, **parameters):
        self.calls.append((query, parameters))
        return _RecordingResult(self.index_properties if "SHOW INDEXES" in query else None, self.records)


class _RecordingResult:
    def __init__(self, index_properties: list[str] | None, records: list[dict]) -> None:
        self.index_properties = index_properties
        self.records = records

    def single(self):
        return {"properties": self.index_properties} if self.index_properties is not None else None

    def __iter__(self):
        return iter(self.records)


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


class _ChatCompletionClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **parameters):
        message = SimpleNamespace(content=json.dumps(self.payload))
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


def _write_catalog_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "Project Name",
        "Doc ID",
        "Source File",
        "Document No",
        "Title",
        "Equipment",
        "Building",
        "System",
        "Study/Survey",
        "Others",
        "Deliverable",
        "Text Content",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
