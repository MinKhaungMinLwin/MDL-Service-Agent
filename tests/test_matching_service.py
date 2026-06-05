"""Focused tests for ITB depth to MDL matching."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from common.text_normalizer import expand_abbreviation_terms
from matching_service.cli import _files_to_process, _json_files_to_process, _scoped_output_dir
from matching_service.models import MatchingConfig
from matching_service.query import (
    build_cross_encoder_query,
    build_depth_filter_query,
    build_fulltext_query,
    build_semantic_query,
    get_keyword_terms,
)
from matching_service.ranking import (
    CrossEncoderReranker,
    TransformersSequenceClassificationReranker,
    build_candidate_text,
    resolve_reranker_backend,
)
from matching_service.repository import MDLSearchRepository
from matching_service.retrieval import DepthRetriever
from matching_service.service import MatchingService
from schedule_service.candidate.candidate_extractor import _parse_matched_doc


class MatchingServiceTest(unittest.TestCase):
    def test_builds_depth_only_queries(self) -> None:
        query, terms = build_depth_filter_query(_source_row())

        self.assertEqual(
            query,
            '"Building Services" OR HVAC OR "Fresh Air Intake" OR "Heating Ventilating and Air Conditioning"',
        )
        self.assertEqual(
            build_cross_encoder_query(terms, ["Fresh Air Intake"]),
            "Depth:\nBuilding Services > HVAC > Fresh Air Intake\n\n"
            "Keywords:\nFresh Air Intake\n\n"
            "Expanded terms:\nHeating Ventilating and Air Conditioning",
        )
        self.assertEqual(build_fulltext_query(["Fresh Air Intake"]), '"Fresh Air Intake"')
        self.assertEqual(
            build_semantic_query(terms, ["Fresh Air Intake"]),
            "Building Services, HVAC, Fresh Air Intake, Heating Ventilating and Air Conditioning",
        )

    def test_expands_only_detected_abbreviation_tokens(self) -> None:
        self.assertEqual(
            expand_abbreviation_terms(["GTG cooling air", "TARGET"]),
            ["GTG cooling air", "TARGET", "Gas Turbine Generator cooling air"],
        )

    def test_full_chunk_cross_encoder_query_keeps_structured_context(self) -> None:
        query = build_cross_encoder_query(
            ["Building Services", "HVAC"],
            ["Fresh Air Intake"],
            chunk_text="Contractor shall submit fresh air intake layout.",
            mode="full_chunk",
        )

        self.assertTrue(query.startswith("Chunk Text:\nContractor shall submit fresh air intake layout."))
        self.assertIn("Depth:\nBuilding Services > HVAC", query)
        self.assertIn("Keywords:\nFresh Air Intake", query)

    def test_retrieval_modes_search_with_depth_and_keyword_queries(self) -> None:
        repository = _RetrievalRepository()
        for mode, expected_doc_id in (("keyword", "KW"), ("semantic", "SEM"), ("hybrid", "SEM")):
            with self.subTest(mode=mode):
                result = DepthRetriever(repository, MatchingConfig(retrieval_mode=mode)).retrieve(
                    "HVAC",
                    '"Fresh Air Intake"',
                    "HVAC, Fresh Air Intake",
                    [0.0, 1.0],
                )
                self.assertEqual(result.candidates[0]["doc_id"], expected_doc_id)

        self.assertEqual(repository.fulltext_queries, ["HVAC", '"Fresh Air Intake"', "HVAC", '"Fresh Air Intake"'])
        self.assertEqual(repository.semantic_queries, ["HVAC, Fresh Air Intake", "HVAC, Fresh Air Intake"])
        self.assertEqual(get_keyword_terms(_source_row()), ["Fresh Air Intake"])

    def test_cross_encoder_reranks_and_limits_candidates(self) -> None:
        reranker = object.__new__(CrossEncoderReranker)
        reranker.batch_size = 2
        reranker.model = _FakeCrossEncoderModel()

        reranked = reranker.rerank(
            "HVAC",
            [
                {"doc_id": "A", "retrieval_rank": 1, "title": "General HVAC"},
                {"doc_id": "B", "retrieval_rank": 2, "title": "Fresh Air Intake"},
                {"doc_id": "C", "retrieval_rank": 3, "title": "Building Services"},
            ],
            top_k=2,
        )

        self.assertEqual([(item["doc_id"], item["final_rank"]) for item in reranked], [("B", 1), ("C", 2)])

    def test_cross_encoder_candidate_text_includes_other_scope(self) -> None:
        text = build_candidate_text({"title": "GENERAL ARRANGEMENT", "others": "Fresh Air Intake"})

        self.assertIn("Others: Fresh Air Intake", text)

    def test_cross_encoder_candidate_text_includes_full_text_content(self) -> None:
        text = build_candidate_text(
            {
                "title": "GENERAL ARRANGEMENT",
                "text_content": "This document covers the fresh air intake routing and interface points.",
            }
        )

        self.assertIn(
            "Text Content: This document covers the fresh air intake routing and interface points.",
            text,
        )

    def test_auto_reranker_backend_preserves_current_default(self) -> None:
        self.assertEqual(
            resolve_reranker_backend("cross-encoder/ms-marco-MiniLM-L6-v2", "auto"),
            "sentence_transformers",
        )
        self.assertEqual(
            resolve_reranker_backend("BAAI/bge-reranker-v2-m3", "auto"),
            "transformers",
        )

    def test_transformers_reranker_scores_candidates_with_shared_contract(self) -> None:
        reranker = object.__new__(TransformersSequenceClassificationReranker)
        reranker.batch_size = 2
        reranker.tokenizer = _FakeTokenizer()
        reranker.model = _FakeSequenceClassificationModel()
        reranker.device = None
        reranker._torch = _FakeTorch()

        reranked = reranker.rerank(
            "HVAC",
            [
                {"doc_id": "A", "retrieval_rank": 1, "title": "General HVAC"},
                {"doc_id": "B", "retrieval_rank": 2, "title": "Fresh Air Intake"},
                {"doc_id": "C", "retrieval_rank": 3, "title": "Building Services"},
            ],
            top_k=2,
        )

        self.assertEqual([(item["doc_id"], item["final_rank"]) for item in reranked], [("B", 1), ("C", 2)])

    def test_matching_setup_recreates_stale_fulltext_index(self) -> None:
        conn = _RecordingConnection(index_properties=["title", "text_content"])

        MDLSearchRepository(conn, MatchingConfig()).setup_fulltext_index()

        self.assertIn("DROP INDEX test_mdl_document_fulltext_idx", conn.calls[1][0])
        self.assertIn("CREATE FULLTEXT INDEX test_mdl_document_fulltext_idx", conn.calls[2][0])

    def test_repository_searches_all_sources_by_default(self) -> None:
        conn = _SearchConnection()
        config = MatchingConfig(
            retrieval_candidate_limit=5,
            output_limit=5,
        )

        MDLSearchRepository(conn, config).search_keyword("pump")

        query, parameters = conn.calls[0]
        self.assertIn("size($source_files) = 0 OR node.source_file IN $source_files", query)
        self.assertEqual(parameters["source_files"], [])
        self.assertEqual(parameters["search_limit"], 5)

    def test_repository_can_restrict_search_to_source_files(self) -> None:
        conn = _SearchConnection()
        config = MatchingConfig(
            retrieval_candidate_limit=5,
            output_limit=5,
            source_files=("R&N_MDL.xlsx",),
        )

        repository = MDLSearchRepository(conn, config)
        repository.search_keyword("pump")
        repository.search_semantic([0.1, 0.2], "pump")

        keyword_query, keyword_parameters = conn.calls[0]
        semantic_query, semantic_parameters = conn.calls[1]
        self.assertIn("node.source_file IN $source_files", keyword_query)
        self.assertIn("node.source_file IN $source_files", semantic_query)
        self.assertEqual(keyword_parameters["source_files"], ["R&N_MDL.xlsx"])
        self.assertEqual(semantic_parameters["source_files"], ["R&N_MDL.xlsx"])
        self.assertEqual(keyword_parameters["search_limit"], 100)
        self.assertEqual(semantic_parameters["search_limit"], 100)
        self.assertIn("node.text_content AS text_content", semantic_query)

    def test_default_matching_paths_read_itb_extract_and_write_mode_output(self) -> None:
        files = _files_to_process(
            inputs=None,
            outputs=None,
            input_dir=Path("output/current_test_env/itb_extract"),
            output_dir=Path("output/current_test_env/matching/hybrid"),
        )

        self.assertEqual(
            files,
            [
                (
                    Path("output/current_test_env/itb_extract/itb_extraction_section6.csv"),
                    Path("output/current_test_env/matching/hybrid/output_match_all_projects_section6.csv"),
                ),
                (
                    Path("output/current_test_env/itb_extract/itb_extraction_section7.csv"),
                    Path("output/current_test_env/matching/hybrid/output_match_all_projects_section7.csv"),
                ),
            ],
        )

    def test_project_scoped_matching_writes_to_source_specific_output_dir(self) -> None:
        self.assertEqual(
            _scoped_output_dir(Path("output/current_test_env/matching"), ()),
            Path("output/current_test_env/matching"),
        )
        self.assertEqual(
            _scoped_output_dir(Path("output/current_test_env/matching"), ("R&N_MDL.xlsx",)),
            Path("output/current_test_env/matching/R_N_MDL"),
        )

    def test_rerank_json_paths_write_new_csv_outputs(self) -> None:
        files = _json_files_to_process(
            inputs=None,
            outputs=None,
            input_dir=Path("output/current_test_env/matching/hybrid"),
            output_dir=Path("output/current_test_env/reranked/hybrid"),
        )

        self.assertEqual(
            files,
            [
                (
                    Path("output/current_test_env/matching/hybrid/output_match_all_projects_section6.json"),
                    Path("output/current_test_env/reranked/hybrid/output_match_all_projects_section6.csv"),
                ),
                (
                    Path("output/current_test_env/matching/hybrid/output_match_all_projects_section7.json"),
                    Path("output/current_test_env/reranked/hybrid/output_match_all_projects_section7.csv"),
                ),
            ],
        )

    def test_service_reranks_top_100_and_outputs_top_20(self) -> None:
        reranker = _RecordingReranker()
        service = MatchingService(
            repository=_BulkRepository(),
            cross_encoder_reranker=reranker,
            config=MatchingConfig(retrieval_mode="keyword", cross_encoder_query_mode="structured"),
        )

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.csv"
            output = Path(directory) / "output.csv"
            pd.DataFrame([_source_row()]).to_csv(source, index=False)

            service.match_file(source, output)

            csv_output = pd.read_csv(output)
            json_output = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))

        self.assertEqual(
            reranker.calls,
            [
                (
                    "Depth:\nBuilding Services > HVAC > Fresh Air Intake\n\n"
                    "Keywords:\nFresh Air Intake\n\n"
                    "Expanded terms:\nHeating Ventilating and Air Conditioning",
                    100,
                    20,
                )
            ],
        )
        self.assertIn("Matched_Doc_20", csv_output.columns)
        self.assertNotIn("Matched_Doc_21", csv_output.columns)
        self.assertIn("[Sample] 1 - Doc 1", csv_output.loc[0, "Matched_Doc_1"])
        self.assertEqual(json_output[0]["retrieval_candidate_count"], 100)
        self.assertEqual(json_output[0]["cross_encoder_candidate_count"], 100)
        self.assertEqual(len(json_output[0]["retrieval_candidates"]), 100)
        self.assertEqual(
            json_output[0]["retrieval_candidates"][0],
            {
                "rank": 1,
                "retrieval_rank": 1,
                "doc_id": "1",
                "source_file": "Sample_MDL.xlsx",
                "document_no": "1",
                "title": "Doc 1",
                "equipment": "",
                "building": "",
                "system": "",
                "study_survey": "",
                "others": "",
                "deliverable": "",
                "text_content": "Full text for doc 1",
                "bm25_rank": 1,
                "semantic_rank": None,
                "bm25_score": 300.0,
                "keyword_rrf_score": 0.03278688524590164,
                "keyword_score": None,
                "semantic_score": None,
                "rrf_score": None,
                "matched_terms": [],
            },
        )
        self.assertEqual(len(json_output[0]["candidates"]), 20)
        self.assertEqual(json_output[0]["candidates"][0]["text_content"], "Full text for doc 1")

    def test_service_can_rerank_existing_structured_output(self) -> None:
        reranker = _RecordingReranker()
        service = MatchingService(
            repository=None,
            cross_encoder_reranker=reranker,
            config=MatchingConfig(retrieval_mode="hybrid", cross_encoder_query_mode="full_chunk"),
        )

        record = {
            "document": "R&N_ITB",
            "chunk_id": "chunk-1",
            "page": "97",
            "depths": {"1st Depth": "Building Services", "2nd Depth": "HVAC", "3rd Depth": "Fresh Air Intake"},
            "depth_context": "HVAC Fresh Air Intake",
            "depth_filter_query": "HVAC",
            "depth_filter_terms": ["Building Services", "HVAC", "Fresh Air Intake"],
            "keyword_filter_query": '"Fresh Air Intake"',
            "semantic_query": "Building Services, HVAC, Fresh Air Intake",
            "vector_terms": "Building Services, HVAC, Fresh Air Intake",
            "retrieval_mode": "hybrid",
            "retrieval_candidate_count": 2,
            "keyword_candidate_count": 2,
            "semantic_candidate_count": 2,
            "cross_encoder_query_mode": "full_chunk",
            "cross_encoder_query": "Chunk Text:\nFull ITB requirement text.",
            "cross_encoder_candidate_count": 2,
            "keywords": "Fresh Air Intake",
            "retrieval_candidates": [
                {
                    "rank": 1,
                    "retrieval_rank": 1,
                    "doc_id": "A",
                    "source_file": "Sample_MDL.xlsx",
                    "document_no": "1",
                    "title": "Doc 1",
                    "text_content": "Full text for doc 1",
                },
                {
                    "rank": 2,
                    "retrieval_rank": 2,
                    "doc_id": "B",
                    "source_file": "Sample_MDL.xlsx",
                    "document_no": "2",
                    "title": "Doc 2",
                    "text_content": "Full text for doc 2",
                },
            ],
            "candidates": [],
        }

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            output = Path(directory) / "output.csv"
            source.write_text(json.dumps([record]), encoding="utf-8")

            service.rerank_json_file(source, output)

            csv_output = pd.read_csv(output)
            json_output = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))

        self.assertEqual(reranker.calls, [("Chunk Text:\nFull ITB requirement text.", 2, 20)])
        self.assertEqual(csv_output.loc[0, "Cross_Encoder_Query"], "Chunk Text:\nFull ITB requirement text.")
        self.assertEqual(json_output[0]["candidates"][0]["doc_id"], "A")

    def test_service_can_rerank_with_full_chunk_text(self) -> None:
        reranker = _RecordingReranker()
        service = MatchingService(
            repository=_BulkRepository(),
            cross_encoder_reranker=reranker,
            config=MatchingConfig(retrieval_mode="keyword", cross_encoder_query_mode="full_chunk"),
        )

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.csv"
            output = Path(directory) / "output.csv"
            pd.DataFrame([{**_source_row(), "Chunk Text": "Full ITB requirement text."}]).to_csv(source, index=False)

            service.match_file(source, output)

            csv_output = pd.read_csv(output)
            json_output = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))

        self.assertTrue(reranker.calls[0][0].startswith("Chunk Text:\nFull ITB requirement text."))
        self.assertEqual(csv_output.loc[0, "Cross_Encoder_Query_Mode"], "full_chunk")
        self.assertEqual(json_output[0]["cross_encoder_query_mode"], "full_chunk")

    def test_schedule_candidate_parser_accepts_cross_encoder_score(self) -> None:
        candidate = _parse_matched_doc(
            "[Fadhili] GTG - P&I DIAGRAM FOR COOLING AIR COOLER "
            "(CrossEncoder: 1.2500 / BM25: 0.9000 / RRF: 0.0320)"
        )
        legacy_candidate = _parse_matched_doc(
            "[Fadhili] GTG - P&I DIAGRAM FOR COOLING AIR COOLER "
            "(최종점수: 0.9100 / 기본: 0.7400)"
        )

        self.assertEqual(candidate["score"], 1.25)
        self.assertEqual(candidate["equipment"], "Gas Turbine Generator")
        self.assertEqual(candidate["title"], "P&I DIAGRAM FOR COOLING AIR COOLER")
        self.assertEqual(candidate["deliverable"], "P&I DIAGRAM")
        self.assertEqual(legacy_candidate["score"], 0.91)
        self.assertEqual(legacy_candidate["title"], "P&I DIAGRAM FOR COOLING AIR COOLER")

        candidate_with_document_no = _parse_matched_doc(
            "[Fadhili] GRT-YK09-P0MA-200051 - GTG - P&I DIAGRAM FOR COOLING AIR COOLER "
            "(CrossEncoder: 1.2500 / BM25: 0.9000 / RRF: 0.0320)"
        )
        self.assertEqual(candidate_with_document_no["document_no"], "GRT-YK09-P0MA-200051")
        self.assertEqual(candidate_with_document_no["equipment"], "Gas Turbine Generator")
        self.assertEqual(candidate_with_document_no["title"], "P&I DIAGRAM FOR COOLING AIR COOLER")


class _RetrievalRepository:
    def __init__(self) -> None:
        self.fulltext_queries: list[str] = []
        self.semantic_queries: list[str] = []

    def search_keyword(self, query: str) -> list[dict]:
        self.fulltext_queries.append(query)
        return [
            {
                "doc_id": "KW",
                "title": "General HVAC",
                "embedding": [1.0, 0.0],
                "bm25_rank": 1,
                "retrieval_rank": 1,
                "bm25_score": 10.0,
            },
            {
                "doc_id": "BOTH",
                "title": "Fresh Air Intake",
                "embedding": [0.7, 0.7],
                "bm25_rank": 2,
                "retrieval_rank": 2,
                "bm25_score": 9.0,
            },
            {
                "doc_id": "SEM",
                "title": "Air filtration",
                "embedding": [0.0, 1.0],
                "bm25_rank": 3,
                "retrieval_rank": 3,
                "bm25_score": 8.0,
            },
        ]

    def search_semantic(self, embedding: list[float], term: str) -> list[dict]:
        self.semantic_queries.append(term)
        return [
            {
                "doc_id": "SEM",
                "title": "Air filtration",
                "semantic_rank": 1,
                "retrieval_rank": 1,
                "semantic_score": 0.99,
                "matched_terms": [term],
            },
            {
                "doc_id": "BOTH",
                "title": "Fresh Air Intake",
                "semantic_rank": 2,
                "retrieval_rank": 2,
                "semantic_score": 0.95,
                "matched_terms": [term],
            },
        ]


class _BulkRepository:
    def search_keyword(self, query: str) -> list[dict]:
        return [
            {
                "doc_id": str(index),
                "source_file": "Sample_MDL.xlsx",
                "document_no": str(index),
                "title": f"Doc {index}",
                "text_content": f"Full text for doc {index}",
                "bm25_rank": index,
                "retrieval_rank": index,
                "bm25_score": float(301 - index),
            }
            for index in range(1, 551)
        ]

    def search_semantic(self, embedding: list[float], term: str) -> list[dict]:
        return []


class _FakeCrossEncoderModel:
    def predict(self, pairs, batch_size: int, show_progress_bar: bool) -> list[float]:
        return [0.25, 0.95, 0.50]


class _FakeTokenizer:
    def __call__(self, queries, candidates, padding: bool, truncation: bool, return_tensors: str):
        return {"queries": queries, "candidates": candidates}


class _FakeSequenceClassificationModel:
    def __init__(self) -> None:
        self.config = type("Config", (), {"num_labels": 1})()

    def __call__(self, **encoded_inputs):
        candidates = encoded_inputs["candidates"]
        score_map = {
            "Title: General HVAC": 0.25,
            "Title: Fresh Air Intake": 0.95,
            "Title: Building Services": 0.50,
        }
        logits = [[score_map[candidate]] for candidate in candidates]
        return type("Output", (), {"logits": _FakeTensor(logits)})()


class _FakeTensor:
    def __init__(self, values):
        self.values = values

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class _FakeNoGrad:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


class _FakeTorch:
    def no_grad(self):
        return _FakeNoGrad()


class _RecordingReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def rerank(self, query_text: str, candidates: list[dict], top_k: int) -> list[dict]:
        self.calls.append((query_text, len(candidates), top_k))
        return [
            {**item, "cross_encoder_score": float(201 - index), "final_rank": index}
            for index, item in enumerate(candidates[:top_k], start=1)
        ]


class _RecordingConnection:
    def __init__(self, index_properties: list[str]) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.index_properties = index_properties

    def session(self):
        return _RecordingSession(self.calls, self.index_properties)


class _RecordingSession:
    def __init__(self, calls: list[tuple[str, dict]], index_properties: list[str]) -> None:
        self.calls = calls
        self.index_properties = index_properties

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def run(self, query: str, **parameters):
        self.calls.append((query, parameters))
        return _RecordingResult(self.index_properties if "SHOW INDEXES" in query else None)


class _RecordingResult:
    def __init__(self, index_properties: list[str] | None) -> None:
        self.index_properties = index_properties

    def single(self):
        return {"properties": self.index_properties} if self.index_properties is not None else None


class _SearchConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def session(self):
        return _SearchSession(self.calls)


class _SearchSession:
    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def run(self, query: str, **parameters):
        self.calls.append((query, parameters))
        return []


def _source_row() -> dict[str, str]:
    return {
        "Document": "R&N_ITB",
        "Page": "97",
        "1st Depth": "Building Services",
        "2nd Depth": "HVAC",
        "3rd Depth": "Fresh Air Intake",
        "Keywords": "Fresh Air Intake",
        "Chunk Text": "ignored",
    }


if __name__ == "__main__":
    unittest.main()
