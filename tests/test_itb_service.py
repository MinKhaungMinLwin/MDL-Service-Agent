"""Focused tests for ITB extraction services."""

from __future__ import annotations

import csv
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from common.llm_json import parse_json_output
from itb_service.cli import _infer_document_name, _resolve_sections, _safe_scope_name
from itb_service.extraction import fallback_search_query, parse_batch_results
from itb_service.loader import (
    clean_chunk_document,
    find_known_abbreviations,
    is_noise_chunk,
    load_target_chunks,
    normalize_hierarchy,
    prepare_chunks,
)
from itb_service.models import OUTPUT_HEADER, ITBExtractionConfig, ITBTarget
from itb_service.output import build_csv_row, build_json_record, build_token_row
from itb_service.service import ITBExtractionService
from itb_service.verification import build_verification_payload

LONG_GT_TEXT = "GT and HRSG requirements shall support safe and reliable plant operation and maintenance."
LONG_ACC_TEXT = "ACC requirements shall support safe and reliable plant operation and maintenance."
LONG_FRESH_AIR_TEXT = (
    "Fresh air intake ventilation requirements shall support safe operation and long-term maintainability."
)
LONG_CONTROL_TEXT = "Plant control system requirements shall support safe operation and long-term maintainability."


class ITBServiceTest(unittest.TestCase):
    def test_loads_target_pages_and_prepares_non_empty_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chunks_path = Path(directory) / "chunks.json"
            chunks_path.write_text(
                json.dumps(
                    {
                        "chunks": [
                            _chunk("outside", [78], "outside"),
                            _chunk("empty", [79], " "),
                            _chunk(
                                "target",
                                [80],
                                LONG_GT_TEXT,
                            ),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            target = ITBTarget(chunks_path, "R&N_ITB", 79, 97)
            chunks = load_target_chunks(target)
            prepared = prepare_chunks("R&N_ITB", chunks, {"GT": "Gas Turbine", "HRSG": "HRSG"})

        self.assertEqual([chunk["chunk_id"] for chunk in chunks], ["target"])
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0].hierarchy, "6._DESIGN_AND_OPERATIONAL_REQUIREMENTS")
        self.assertEqual(prepared[0].known_abbreviations, {"GT": "Gas Turbine"})

    def test_loads_all_target_chunks_without_page_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chunks_path = Path(directory) / "chunks.json"
            chunks_path.write_text(
                json.dumps(
                    {
                        "chunks": [
                            _chunk("first", [1], "General requirements"),
                            _chunk(
                                "second",
                                [120],
                                LONG_ACC_TEXT,
                            ),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            chunks = load_target_chunks(ITBTarget(chunks_path, "Fadhili_ITB"))

        self.assertEqual([chunk["chunk_id"] for chunk in chunks], ["second"])

    def test_cleans_noise_chunks_before_extraction(self) -> None:
        good_chunk = _chunk(
            "good",
            [10],
            "The Contractor shall provide all required equipment for safe and reliable plant operation.",
        )
        toc_chunk = {**_chunk("toc", [2], "1. Introduction ........ 20"), "chunk_type": "toc"}
        index_chunk = {
            **_chunk("index", [2], "Document index with enough words to look long."),
            "label": ["document_index"],
        }
        separator_chunk = _chunk("separator", [1], "----------------------------------------")

        cleaned = clean_chunk_document({"chunks": [good_chunk, toc_chunk, index_chunk, separator_chunk]})

        self.assertFalse(is_noise_chunk(good_chunk))
        self.assertEqual([chunk["chunk_id"] for chunk in cleaned["chunks"]], ["good"])

    def test_cli_helpers_infer_document_scope_and_sections(self) -> None:
        self.assertEqual(_infer_document_name(Path("Turkistan ITB_chunks.json")), "Turkistan_ITB")
        self.assertEqual(_safe_scope_name("R&N_ITB"), "R_N_ITB")
        self.assertEqual(_resolve_sections("all", "7"), ["all"])
        self.assertEqual(_resolve_sections("section", "6,7"), ["6", "7"])

    def test_normalizes_hierarchy_abbreviations_and_fallback_query(self) -> None:
        hierarchy = normalize_hierarchy("test_temp > R&N_ITB > 7.5_HVAC, Systems", "R&N_ITB")
        abbreviations = find_known_abbreviations("GTG and GT are separate.", {"GT": "Gas Turbine"})
        query = fallback_search_query(["General", "7.5_HVAC", "Fresh Air Intake"], "SMACNA, NFPA 90A")

        self.assertEqual(hierarchy, "7.5_HVAC  Systems")
        self.assertEqual(abbreviations, {"GT": "Gas Turbine"})
        self.assertEqual(query, "HVAC Fresh Air Intake SMACNA NFPA 90A")

    def test_parses_batch_results_and_builds_matching_csv_contract(self) -> None:
        parsed = parse_json_output('{"results":[{"chunk_id":"chunk-1","depth_1":"HVAC"}]}')
        results = parse_batch_results(parsed, [{"chunk_id": "chunk-1"}])
        row = build_csv_row(
            "R&N_ITB",
            _chunk(
                "chunk-1",
                [97],
                f"  {LONG_FRESH_AIR_TEXT}  ",
            ),
            "Building Services > HVAC",
            {"depth_1": "Building Services", "depth_2": "HVAC", "keywords": ["Fresh Air Intake"]},
        )

        self.assertEqual(results["chunk-1"]["depth_1"], "HVAC")
        self.assertEqual(dict(zip(OUTPUT_HEADER, row, strict=True))["Search Query Source"], "fallback")
        self.assertEqual(
            dict(zip(OUTPUT_HEADER, row, strict=True))["Search Query"],
            "Building Services HVAC Fresh Air Intake",
        )
        self.assertEqual(
            dict(zip(OUTPUT_HEADER, row, strict=True))["Chunk Text"],
            f"  {LONG_FRESH_AIR_TEXT}  ",
        )

    def test_empty_single_chunk_response_is_not_treated_as_valid(self) -> None:
        self.assertEqual(parse_batch_results({}, [{"chunk_id": "chunk-1"}]), {})

    def test_verification_payload_includes_known_abbreviations(self) -> None:
        payload = build_verification_payload(
            "R&N_ITB",
            _chunk("chunk-1", [95], "GSUT outage modes"),
            "6.6 Plant Performance",
            {"GSUT": "Generator Step-Up Transformer"},
            {"depth_1": "Plant Performance"},
        )

        self.assertEqual(payload["source_input"]["known_abbreviations"], {"GSUT": "Generator Step-Up Transformer"})

    def test_service_writes_verified_csv_json_and_token_outputs(self) -> None:
        client = _ChatClient(
            [
                {
                    "results": [
                        {
                            "chunk_id": "chunk-1",
                            "depth_1": "Building Services",
                            "depth_2": "HVAC",
                            "depth_3": "Fresh Air Intake",
                            "keywords": ["SMACNA"],
                            "search_query": "HVAC, Fresh Air Intake, SMACNA",
                            "confidence": "high",
                            "needs_review": False,
                        }
                    ]
                },
                {
                    "results": [
                        {
                            "chunk_id": "chunk-1",
                            "is_valid": True,
                            "severity": "ok",
                            "issues": [],
                        }
                    ]
                },
            ]
        )
        config = ITBExtractionConfig(model="deployment", enable_verification=True, batch_delay_seconds=0)
        service = ITBExtractionService(client, config, "extract prompt", {}, "verify prompt", sleep=lambda _: None)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            chunks_path = base / "chunks.json"
            chunks_path.write_text(
                json.dumps(
                    {
                        "chunks": [
                            _chunk(
                                "chunk-1",
                                [97],
                                LONG_FRESH_AIR_TEXT,
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            count = service.extract_to_files(
                [ITBTarget(chunks_path, "R&N_ITB", 97, 124)],
                base / "output.csv",
                base / "output.json",
                base / "tokens.csv",
            )
            with open(base / "output.csv", newline="", encoding="utf-8-sig") as file:
                csv_rows = list(csv.DictReader(file))
            json_rows = json.loads((base / "output.json").read_text(encoding="utf-8"))
            with open(base / "tokens.csv", newline="", encoding="utf-8-sig") as file:
                token_rows = list(csv.DictReader(file))

        self.assertEqual(count, 1)
        self.assertEqual(csv_rows[0]["LLM Verify Valid"], "True")
        self.assertEqual(json_rows[0]["llm_verification"]["severity"], "ok")
        self.assertEqual(token_rows[0]["Total Tokens"], "30")
        self.assertEqual(client.prompts, ["extract prompt", "verify prompt"])

    def test_service_marks_missing_model_results_for_review(self) -> None:
        client = _ChatClient([{"results": []}])
        config = ITBExtractionConfig(model="deployment", batch_delay_seconds=0)
        service = ITBExtractionService(client, config, "extract prompt", {}, sleep=lambda _: None)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            chunks_path = base / "chunks.json"
            chunks_path.write_text(
                json.dumps(
                    {
                        "chunks": [
                            _chunk(
                                "chunk-1",
                                [97],
                                LONG_FRESH_AIR_TEXT,
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            service.extract_to_files(
                [ITBTarget(chunks_path, "R&N_ITB", 97, 124)],
                base / "output.csv",
                base / "output.json",
                base / "tokens.csv",
            )
            json_rows = json.loads((base / "output.json").read_text(encoding="utf-8"))

        self.assertEqual(json_rows[0]["llm_output"]["depth_1"], "ERROR")
        self.assertIn("Missing model result", json_rows[0]["error"])

    def test_service_resumes_existing_outputs_by_chunk_id(self) -> None:
        client = _ChatClient([{"results": [{"chunk_id": "chunk-2", "depth_1": "HVAC"}]}])
        config = ITBExtractionConfig(model="deployment", batch_delay_seconds=0)
        service = ITBExtractionService(client, config, "extract prompt", {}, sleep=lambda _: None)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            chunks_path = base / "chunks.json"
            chunks_path.write_text(
                json.dumps(
                    {
                        "chunks": [
                            _chunk("chunk-1", [97], LONG_FRESH_AIR_TEXT),
                            _chunk("chunk-2", [98], LONG_CONTROL_TEXT),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (base / "output.json").write_text(
                json.dumps(
                    [
                        {
                            "document": "R&N_ITB",
                            "chunk_id": "chunk-1",
                            "llm_output": {"depth_1": "Existing"},
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (base / "output.csv").write_text(
                "\ufeffDocument,Chunk ID\nR&N_ITB,chunk-1\n",
                encoding="utf-8",
            )
            (base / "tokens.csv").write_text(
                "\ufeffDocument,Page,Prompt Tokens,Completion Tokens,Total Tokens,Chunk Text\n"
                "R&N_ITB,97,1,1,2,existing\n",
                encoding="utf-8",
            )
            count = service.extract_to_files(
                [ITBTarget(chunks_path, "R&N_ITB", 97, 124)],
                base / "output.csv",
                base / "output.json",
                base / "tokens.csv",
            )
            json_rows = json.loads((base / "output.json").read_text(encoding="utf-8"))

        self.assertEqual(count, 1)
        self.assertEqual([row["chunk_id"] for row in json_rows], ["chunk-1", "chunk-2"])
        self.assertEqual(client.prompts, ["extract prompt"])

    def test_service_keeps_output_order_with_concurrent_batches(self) -> None:
        config = ITBExtractionConfig(model="deployment", batch_delay_seconds=0, max_concurrency=2)
        service = _OutOfOrderITBExtractionService(None, config, "extract prompt", {}, sleep=lambda _: None)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            chunks_path = base / "chunks.json"
            chunks_path.write_text(
                json.dumps(
                    {
                        "chunks": [
                            _chunk("chunk-1", [97], LONG_FRESH_AIR_TEXT),
                            _chunk("chunk-2", [98], LONG_CONTROL_TEXT),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            count = service.extract_to_files(
                [ITBTarget(chunks_path, "R&N_ITB", 97, 124)],
                base / "output.csv",
                base / "output.json",
                base / "tokens.csv",
            )
            with open(base / "output.csv", newline="", encoding="utf-8-sig") as file:
                csv_rows = list(csv.DictReader(file))
            json_rows = json.loads((base / "output.json").read_text(encoding="utf-8"))

        self.assertEqual(count, 2)
        self.assertEqual([row["Chunk ID"] for row in csv_rows], ["chunk-1", "chunk-2"])
        self.assertEqual([row["chunk_id"] for row in json_rows], ["chunk-1", "chunk-2"])

    def test_service_marks_missing_verification_results_as_errors(self) -> None:
        client = _ChatClient(
            [
                {"results": [{"chunk_id": "chunk-1", "depth_1": "HVAC"}]},
                {"results": []},
            ]
        )
        config = ITBExtractionConfig(model="deployment", enable_verification=True, batch_delay_seconds=0)
        service = ITBExtractionService(client, config, "extract prompt", {}, "verify prompt", sleep=lambda _: None)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            chunks_path = base / "chunks.json"
            chunks_path.write_text(
                json.dumps(
                    {
                        "chunks": [
                            _chunk(
                                "chunk-1",
                                [97],
                                LONG_FRESH_AIR_TEXT,
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            service.extract_to_files(
                [ITBTarget(chunks_path, "R&N_ITB", 97, 124)],
                base / "output.csv",
                base / "output.json",
                base / "tokens.csv",
            )
            json_rows = json.loads((base / "output.json").read_text(encoding="utf-8"))

        self.assertEqual(json_rows[0]["llm_verification"]["severity"], "error")
        self.assertIn("Missing model verification result", json_rows[0]["llm_verification"]["issues"][0])

    def test_service_writes_section_boundary_rejections_to_audit_outputs(self) -> None:
        client = _ChatClient(
            [
                {
                    "results": [
                        {
                            "chunk_id": "chunk-1",
                            "belongs_to_requested_section": False,
                            "actual_section": "8 Plant Control and Operational System",
                            "section_boundary_reason": "Chunk starts the next top-level section.",
                            "depth_1": "Plant Control and Operational System",
                            "depth_2": "Process Control System",
                            "keywords": ["DCS"],
                            "confidence": "high",
                            "needs_review": False,
                        }
                    ]
                },
            ]
        )
        config = ITBExtractionConfig(model="deployment", batch_delay_seconds=0, requested_section="7")
        service = ITBExtractionService(client, config, "extract prompt", {}, sleep=lambda _: None)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            chunks_path = base / "chunks.json"
            chunks_path.write_text(
                json.dumps(
                    {
                        "chunks": [
                            _chunk(
                                "chunk-1",
                                [124],
                                LONG_CONTROL_TEXT,
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            count = service.extract_to_files(
                [ITBTarget(chunks_path, "R&N_ITB", 97, 124)],
                base / "output.csv",
                base / "output.json",
                base / "tokens.csv",
                base / "rejected.csv",
                base / "rejected.json",
            )
            with open(base / "output.csv", newline="", encoding="utf-8-sig") as file:
                csv_rows = list(csv.DictReader(file))
            with open(base / "rejected.csv", newline="", encoding="utf-8-sig") as file:
                rejected_rows = list(csv.DictReader(file))
            rejected_json_rows = json.loads((base / "rejected.json").read_text(encoding="utf-8"))

        self.assertEqual(count, 0)
        self.assertEqual(csv_rows, [])
        self.assertEqual(rejected_rows[0]["Requested Section"], "7")
        self.assertEqual(rejected_rows[0]["Actual Section"], "8 Plant Control and Operational System")
        self.assertEqual(rejected_json_rows[0]["llm_output"]["keywords"], ["DCS"])
        self.assertEqual(client.prompts, ["extract prompt"])


class _ChatClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.prompts = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **parameters):
        self.prompts.append(parameters["messages"][0]["content"])
        payload = self.responses.pop(0)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        message = SimpleNamespace(content=json.dumps(payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class _OutOfOrderITBExtractionService(ITBExtractionService):
    def _extract_batch(self, document_name, batch):
        item = batch[0]
        chunk_id = item.chunk["chunk_id"]
        if chunk_id == "chunk-1":
            time.sleep(0.05)
        extraction = {"depth_1": chunk_id}
        return (
            [build_csv_row(document_name, item.chunk, item.hierarchy, extraction)],
            [build_json_record(document_name, item.chunk, item.hierarchy, extraction, {}, item.known_abbreviations)],
            [build_token_row(document_name, item.chunk, {})],
            [],
            [],
        )


def _chunk(chunk_id: str, pages: list[int], text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "section": "6._DESIGN_AND_OPERATIONAL_REQUIREMENTS",
        "hierarchy_context": "test_temp > R&N_ITB > 6._DESIGN_AND_OPERATIONAL_REQUIREMENTS",
        "section_path": [6],
        "page_num": pages,
        "label": ["text"],
        "chunk_type": "content",
        "chunk_size_tokens": 10,
        "extraction_confidence": None,
    }


if __name__ == "__main__":
    unittest.main()
