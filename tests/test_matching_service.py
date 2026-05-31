"""Focused tests for ITB depth to MDL matching."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from matching_service.models import MatchingConfig
from matching_service.query import build_cross_encoder_query, build_depth_filter_query
from matching_service.ranking import CrossEncoderReranker, build_candidate_text
from matching_service.retrieval import DepthRetriever
from matching_service.service import MatchingService
from schedule_service.candidate_extractor import _parse_matched_doc


class MatchingServiceTest(unittest.TestCase):
    def test_builds_depth_only_queries(self) -> None:
        query, terms = build_depth_filter_query(_source_row())

        self.assertEqual(query, '"Building Services" OR HVAC OR "Fresh Air Intake"')
        self.assertEqual(build_cross_encoder_query(terms), "Building Services > HVAC > Fresh Air Intake")

    def test_retrieval_modes_preserve_their_expected_ranking(self) -> None:
        repository = _RetrievalRepository()
        for mode, expected_doc_id in (("keyword", "KW"), ("semantic", "SEM"), ("hybrid", "BOTH")):
            with self.subTest(mode=mode):
                result = DepthRetriever(repository, MatchingConfig(retrieval_mode=mode)).retrieve(
                    "HVAC",
                    [("HVAC", [1.0])],
                )
                self.assertEqual(result.candidates[0]["doc_id"], expected_doc_id)

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

    def test_service_reranks_top_200_and_outputs_top_100(self) -> None:
        reranker = _RecordingReranker()
        service = MatchingService(
            repository=_BulkRepository(),
            cross_encoder_reranker=reranker,
            config=MatchingConfig(retrieval_mode="keyword"),
        )

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.csv"
            output = Path(directory) / "output.csv"
            pd.DataFrame([_source_row()]).to_csv(source, index=False)

            service.match_file(source, output)

            csv_output = pd.read_csv(output)
            json_output = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))

        self.assertEqual(reranker.calls, [("Building Services > HVAC > Fresh Air Intake", 200, 100)])
        self.assertIn("Matched_Doc_100", csv_output.columns)
        self.assertNotIn("Matched_Doc_101", csv_output.columns)
        self.assertEqual(json_output[0]["retrieval_candidate_count"], 250)
        self.assertEqual(json_output[0]["cross_encoder_candidate_count"], 200)
        self.assertEqual(len(json_output[0]["candidates"]), 100)

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


class _RetrievalRepository:
    def search_keyword(self, query: str) -> list[dict]:
        return [
            {"doc_id": "KW", "bm25_rank": 1, "retrieval_rank": 1, "bm25_score": 10.0},
            {"doc_id": "BOTH", "bm25_rank": 2, "retrieval_rank": 2, "bm25_score": 9.0},
        ]

    def search_semantic(self, embedding: list[float], term: str) -> list[dict]:
        return [
            {
                "doc_id": "SEM",
                "semantic_rank": 1,
                "retrieval_rank": 1,
                "semantic_score": 0.99,
                "matched_terms": [term],
            },
            {
                "doc_id": "BOTH",
                "semantic_rank": 2,
                "retrieval_rank": 2,
                "semantic_score": 0.80,
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
                "bm25_rank": index,
                "retrieval_rank": index,
                "bm25_score": float(301 - index),
            }
            for index in range(1, 251)
        ]

    def search_semantic(self, embedding: list[float], term: str) -> list[dict]:
        return []


class _FakeCrossEncoderModel:
    def predict(self, pairs, batch_size: int, show_progress_bar: bool) -> list[float]:
        return [0.25, 0.95, 0.50]


class _RecordingReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def rerank(self, query_text: str, candidates: list[dict], top_k: int) -> list[dict]:
        self.calls.append((query_text, len(candidates), top_k))
        return [
            {**item, "cross_encoder_score": float(201 - index), "final_rank": index}
            for index, item in enumerate(candidates[:top_k], start=1)
        ]


def _source_row() -> dict[str, str]:
    return {
        "Document": "R&N_ITB",
        "Page": "97",
        "1st Depth": "Building Services",
        "2nd Depth": "HVAC",
        "3rd Depth": "Fresh Air Intake",
        "Keywords": "ignored",
        "Search Query": "ignored",
        "Chunk Text": "ignored",
    }


if __name__ == "__main__":
    unittest.main()
