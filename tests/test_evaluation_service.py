"""Focused tests for LLM-assisted matching ground truth."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation_service.ground_truth.cli import _discover_sections
from evaluation_service.ground_truth.service import (
    EvaluationConfig,
    GroundTruthService,
    _resolve_judgments,
    _resolve_verifications,
    build_candidate_pool,
    iter_judge_pairs,
)


class EvaluationServiceTest(unittest.TestCase):
    def test_cli_discovers_available_extract_sections_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "output_itb_section10_focused.csv").write_text("Chunk ID,Chunk Text\n", encoding="utf-8")
            (base / "output_itb_section2_focused.csv").write_text("Chunk ID,Chunk Text\n", encoding="utf-8")
            (base / "output_itb_sectionA_focused.csv").write_text("Chunk ID,Chunk Text\n", encoding="utf-8")

            self.assertEqual(_discover_sections(base), ("2", "10", "A"))

    def test_pool_merges_modes_deduplicates_docs_and_blinds_judge_pairs(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"6:chunk-1": {"Chunk Text": "Steam turbine foundation requirement"}},
            records_by_source={
                ("6", "keyword"): [_matching_record("chunk-1", [_candidate("A", 1.0), _candidate("B", 0.5)])],
                ("6", "semantic"): [_matching_record("chunk-1", [_candidate("B", 0.9), _candidate("C", 0.8)])],
            },
            top_k=2,
        )
        pairs = iter_judge_pairs(pools)

        self.assertEqual(len(pools), 1)
        self.assertEqual({candidate["doc_id"] for candidate in pools[0]["candidates"]}, {"A", "B", "C"})
        candidate_b = next(candidate for candidate in pools[0]["candidates"] if candidate["doc_id"] == "B")
        self.assertEqual(candidate_b["source_modes"], ["keyword", "semantic"])
        self.assertEqual(candidate_b["source_ranks"], {"keyword": 2, "semantic": 1})
        self.assertEqual({pair["mdl"]["doc_id"] for pair in pairs}, {"A", "B", "C"})
        self.assertNotIn("cross_encoder_score", pairs[0]["mdl"])
        self.assertNotIn("source_modes", pairs[0]["mdl"])

    def test_service_resumes_existing_judgments_and_verifies_all_rows(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"6:chunk-1": {"Chunk Text": "Steam turbine foundation requirement"}},
            records_by_source={
                ("6", "hybrid"): [_matching_record("chunk-1", [_candidate("A", 1.0), _candidate("B", 0.5)])],
            },
            top_k=2,
        )
        pair_by_doc = {pair["mdl"]["doc_id"]: pair for pair in iter_judge_pairs(pools)}
        existing_judgment = _judgment(pair_by_doc["A"], relevance=0, confidence=0.95)
        client = _ChatClient(
            [
                {"results": [_judgment(pair_by_doc["B"], relevance=2, confidence=0.9)]},
                {
                    "results": [
                        {
                            "judgment_id": pair_by_doc["A"]["judgment_id"],
                            "relevance": 0,
                            "confidence": 0.95,
                            "agrees": True,
                        },
                        {
                            "judgment_id": pair_by_doc["B"]["judgment_id"],
                            "relevance": 2,
                            "confidence": 0.9,
                            "agrees": True,
                        }
                    ]
                },
            ]
        )
        service = GroundTruthService(
            EvaluationConfig(model="deployment", modes=("hybrid",), verify=True, batch_delay_seconds=0),
            client,
            "judge prompt",
            "verify prompt",
            sleep=lambda _: None,
        )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            judgments_path = base / "judgments.json"
            judgments_path.write_text(json.dumps([existing_judgment]), encoding="utf-8")
            service.judge_to_files(
                pools,
                judgments_path,
                base / "verifications.json",
                base / "ground_truth.csv",
            )
            judgments = json.loads(judgments_path.read_text(encoding="utf-8"))
            verifications = json.loads((base / "verifications.json").read_text(encoding="utf-8"))

        self.assertEqual(len(judgments), 2)
        self.assertEqual([call["messages"][0]["content"] for call in client.calls], ["judge prompt", "verify prompt"])
        self.assertEqual(
            {row["judgment_id"] for row in verifications},
            {pair_by_doc["A"]["judgment_id"], pair_by_doc["B"]["judgment_id"]},
        )

    def test_resolved_judgments_clamp_llm_scores_to_schema(self) -> None:
        pair = {
            "judgment_id": "6:chunk-1:A",
            "section": "6",
            "chunk_id": "chunk-1",
            "mdl": {"doc_id": "A"},
        }

        result = _resolve_judgments(
            [pair],
            [{"judgment_id": pair["judgment_id"], "relevance": 9, "topic_match": -1, "confidence": 2.5}],
        )[0]

        self.assertEqual(result["relevance"], 3)
        self.assertEqual(result["topic_match"], 0)
        self.assertEqual(result["confidence"], 1.0)

    def test_resolved_verifications_clamp_scores_and_require_boolean_agreement(self) -> None:
        result = _resolve_verifications(
            [{"judgment_id": "6:chunk-1:A"}],
            [{"judgment_id": "6:chunk-1:A", "relevance": 9, "confidence": -1, "agrees": "true"}],
        )[0]

        self.assertEqual(result["relevance"], 3)
        self.assertEqual(result["confidence"], 0.0)
        self.assertFalse(result["agrees"])


class _ChatClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls = []
        self.chat = _Chat(self)


class _Chat:
    def __init__(self, client: _ChatClient) -> None:
        self.completions = _Completions(client)


class _Completions:
    def __init__(self, client: _ChatClient) -> None:
        self.client = client

    def create(self, **parameters):
        self.client.calls.append(parameters)
        payload = self.client.responses.pop(0)
        message = type("Message", (), {"content": json.dumps(payload)})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


def _matching_record(chunk_id: str, candidates: list[dict]) -> dict:
    return {
        "document": "R&N_ITB",
        "chunk_id": chunk_id,
        "page": "80",
        "depths": {"1st Depth": "Engineering", "2nd Depth": "Steam Turbine"},
        "keywords": "foundation, design criteria",
        "candidates": candidates,
    }


def _candidate(doc_id: str, score: float) -> dict:
    return {
        "doc_id": doc_id,
        "title": f"Document {doc_id}",
        "equipment": "Steam Turbine",
        "deliverable": "Design Criteria",
        "cross_encoder_score": score,
    }


def _judgment(pair: dict, relevance: int, confidence: float) -> dict:
    return {
        "judgment_id": pair["judgment_id"],
        "section": pair["section"],
        "chunk_id": pair["chunk_id"],
        "mdl_doc_id": pair["mdl"]["doc_id"],
        "relevance": relevance,
        "confidence": confidence,
    }


if __name__ == "__main__":
    unittest.main()
