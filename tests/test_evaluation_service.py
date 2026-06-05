"""Focused tests for LLM-assisted matching ground truth."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation_service.ground_truth.cli import _discover_sections, merge_positive_ground_truth
from evaluation_service.ground_truth.service import (
    EvaluationConfig,
    GroundTruthService,
    _resolve_positive_judgments,
    _resolve_verifications,
    build_candidate_pool,
    build_verified_positive_ground_truth_rows,
    iter_judge_pairs,
    limit_itb_rows,
    load_positive_ground_truth_rows,
)


class EvaluationServiceTest(unittest.TestCase):
    def test_cli_discovers_available_extract_sections_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "output_itb_section10_focused.csv").write_text("Chunk ID,Chunk Text\n", encoding="utf-8")
            (base / "output_itb_section2_focused.csv").write_text("Chunk ID,Chunk Text\n", encoding="utf-8")
            (base / "output_itb_sectionA_focused.csv").write_text("Chunk ID,Chunk Text\n", encoding="utf-8")

            self.assertEqual(_discover_sections(base), ("2", "10", "A"))

    def test_max_itb_chunks_cannot_be_negative(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_itb_chunks cannot be negative"):
            EvaluationConfig(model="deployment", max_itb_chunks=-1)

    def test_evaluation_config_defaults_to_verification(self) -> None:
        self.assertEqual(EvaluationConfig(model="deployment").modes, ("keyword", "semantic", "hybrid"))

    def test_limit_itb_rows_keeps_first_rows_in_section_chunk_order(self) -> None:
        rows = {
            "7:chunk-2": {"Chunk Text": "second"},
            "6:chunk-1": {"Chunk Text": "first"},
            "7:chunk-1": {"Chunk Text": "third"},
        }

        limited = limit_itb_rows(rows, 2)

        self.assertEqual(list(limited), ["6:chunk-1", "7:chunk-1"])

    def test_pool_merges_modes_deduplicates_docs_and_blinds_judge_pairs(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"6:chunk-1": {"Chunk Text": "Steam turbine foundation requirement"}},
            records_by_source={
                ("6", "keyword"): [_matching_record("chunk-1", [_candidate("A", 1.0), _candidate("B", 0.5)])],
                ("6", "semantic"): [_matching_record("chunk-1", [_candidate("B", 0.9), _candidate("C", 0.8)])],
            },
        )
        pairs = iter_judge_pairs(pools)

        self.assertEqual(len(pools), 1)
        self.assertEqual({candidate["doc_id"] for candidate in pools[0]["candidates"]}, {"A", "B", "C"})
        candidate_b = next(candidate for candidate in pools[0]["candidates"] if candidate["doc_id"] == "B")
        self.assertNotIn("embedding", candidate_b)
        self.assertNotIn("cross_encoder_score", candidate_b)
        self.assertNotIn("source_modes", candidate_b)
        self.assertNotIn("source_ranks", candidate_b)
        self.assertEqual({pair["mdl"]["doc_id"] for pair in pairs}, {"A", "B", "C"})
        self.assertNotIn("embedding", pairs[0]["mdl"])
        self.assertNotIn("cross_encoder_score", pairs[0]["mdl"])
        self.assertNotIn("source_modes", pairs[0]["mdl"])

    def test_pool_deduplicates_candidates_by_visible_document_identity(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"6:chunk-1": {"Chunk Text": "Steam turbine foundation requirement"}},
            records_by_source={
                (
                    "6",
                    "hybrid",
                ): [
                    _matching_record(
                        "chunk-1",
                        [
                            _candidate("A-1", 1.0, source_file="Sample_MDL.xlsx", document_no="001", title="Layout"),
                            _candidate("A-2", 0.9, source_file="Sample_MDL.xlsx", document_no="001", title="Layout"),
                        ],
                    )
                ],
            },
        )

        self.assertEqual(len(pools[0]["candidates"]), 1)
        self.assertEqual(pools[0]["candidates"][0]["doc_id"], "A-1")

    def test_pool_uses_all_matching_candidates_without_additional_top_k_cap(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"6:chunk-1": {"Chunk Text": "Steam turbine foundation requirement"}},
            records_by_source={
                (
                    "6",
                    "hybrid",
                ): [
                    _matching_record(
                        "chunk-1",
                        [_candidate("A", 1.0), _candidate("B", 0.9), _candidate("C", 0.8)],
                    )
                ],
            },
        )

        self.assertEqual([candidate["doc_id"] for candidate in pools[0]["candidates"]], ["A", "B", "C"])

    def test_service_selects_and_verifies_positive_rows(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"7:chunk-1": {"Chunk Text": "Cooling water requirement"}},
            records_by_source={
                ("7", "hybrid"): [_matching_record("chunk-1", [_candidate("A", 1.0), _candidate("B", 0.5)])],
            },
        )
        pair_by_doc = {pair["mdl"]["doc_id"]: pair for pair in iter_judge_pairs(pools)}
        client = _ChatClient(
            [
                {
                    "results": [
                        {
                            "section": "7",
                            "chunk_id": "chunk-1",
                            "positive_judgment_ids": [pair_by_doc["A"]["judgment_id"]],
                            "reasons": {pair_by_doc["A"]["judgment_id"]: "Direct cooling water reference."},
                        }
                    ]
                },
                {
                    "results": [
                        {
                            "judgment_id": pair_by_doc["A"]["judgment_id"],
                            "relevance": 3,
                            "agrees": True,
                        }
                    ]
                },
            ]
        )
        service = GroundTruthService(
            EvaluationConfig(model="deployment", modes=("hybrid",), batch_delay_seconds=0),
            client,
            "positive judge prompt",
            "verify prompt",
            sleep=lambda _: None,
        )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            judgments, verifications = service.judge(
                pools,
                resume_state_path=base / "resume_state.json",
            )
            resume_state = json.loads((base / "resume_state.json").read_text(encoding="utf-8"))
            verified_rows = build_verified_positive_ground_truth_rows(judgments, verifications)

        self.assertEqual(len(client.calls), 2)
        judge_payload = json.loads(client.calls[0]["messages"][1]["content"])
        judge_mdl = judge_payload["pools"][0]["candidates"][0]["mdl"]
        self.assertIn("title", judge_mdl)
        self.assertIn("deliverable", judge_mdl)
        self.assertIn("text_content", judge_mdl)
        self.assertNotIn("doc_id", judge_mdl)
        self.assertNotIn("source_file", judge_mdl)
        self.assertNotIn("document", judge_payload["pools"][0]["itb"])
        self.assertNotIn("page", judge_payload["pools"][0]["itb"])
        verify_payload = json.loads(client.calls[1]["messages"][1]["content"])
        self.assertEqual(len(verify_payload["verification_pools"]), 1)
        verify_pool = verify_payload["verification_pools"][0]
        self.assertEqual(verify_pool["chunk_id"], "chunk-1")
        self.assertEqual(len(verify_pool["positive_candidates"]), 1)
        self.assertEqual(verify_pool["positive_candidates"][0]["judgment_id"], pair_by_doc["A"]["judgment_id"])
        self.assertNotIn("doc_id", verify_pool["positive_candidates"][0]["mdl"])
        self.assertEqual(len(resume_state["judgments"]), 1)
        self.assertEqual(len(resume_state["verifications"]), 1)
        self.assertEqual(resume_state["completed_pools"], [{"section": "7", "chunk_id": "chunk-1"}])
        self.assertEqual(len(verified_rows), 1)
        self.assertEqual(verified_rows[0]["mdl_doc_id"], pair_by_doc["A"]["mdl"]["doc_id"])

    def test_resume_remembers_pools_with_no_positive_rows(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"7:chunk-1": {"Chunk Text": "Cooling water requirement"}},
            records_by_source={("7", "hybrid"): [_matching_record("chunk-1", [_candidate("A", 1.0)])]},
        )
        client = _ChatClient(
            [
                {
                    "results": [
                        {
                            "section": "7",
                            "chunk_id": "chunk-1",
                            "positive_judgment_ids": [],
                        }
                    ]
                },
            ]
        )
        service = GroundTruthService(
            EvaluationConfig(
                model="deployment",
                modes=("hybrid",),
                resume=True,
                batch_delay_seconds=0,
            ),
            client,
            "positive judge prompt",
            "verify prompt",
            sleep=lambda _: None,
        )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            resume_state_path = base / "resume_state.json"
            service.judge(pools, resume_state_path)
            service.judge(pools, resume_state_path)
            resume_state = json.loads(resume_state_path.read_text(encoding="utf-8"))

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(resume_state["judgments"], [])
        self.assertEqual(resume_state["completed_pools"], [{"section": "7", "chunk_id": "chunk-1"}])

    def test_merge_positive_ground_truth_updates_final_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            final_path = base / "itb_mdl_matching_ground_truth_final.csv"
            _write_csv(
                final_path,
                ["section", "chunk_id", "mdl_doc_id", "relevance", "final_relevance", "label_status"],
                [
                    {
                        "section": "6",
                        "chunk_id": "chunk-1",
                        "mdl_doc_id": "A",
                        "relevance": "3",
                        "final_relevance": "3",
                        "label_status": "positive",
                    }
                ],
            )
            new_rows = [
                {
                    "section": "6",
                    "chunk_id": "chunk-1",
                    "mdl_doc_id": "A",
                    "relevance": "3",
                    "final_relevance": "3",
                    "label_status": "positive",
                },
                {
                    "section": "7",
                    "chunk_id": "chunk-2",
                    "mdl_doc_id": "B",
                    "relevance": "3",
                    "final_relevance": "3",
                    "label_status": "positive",
                },
            ]

            count = merge_positive_ground_truth(final_path, new_rows)
            rows = load_positive_ground_truth_rows((final_path,))

        self.assertEqual(count, 2)
        self.assertEqual(
            [(row["section"], row["chunk_id"], row["mdl_doc_id"]) for row in rows],
            [("6", "chunk-1", "A"), ("7", "chunk-2", "B")],
        )

    def test_service_retries_when_llm_omits_a_judgment(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"7:chunk-1": {"Chunk Text": "Cooling water requirement"}},
            records_by_source={
                ("7", "hybrid"): [_matching_record("chunk-1", [_candidate("A", 1.0), _candidate("B", 0.5)])],
            },
        )
        pair_by_doc = {pair["mdl"]["doc_id"]: pair for pair in iter_judge_pairs(pools)}
        client = _ChatClient(
            [
                {
                    "results": [
                        {
                            "section": "7",
                            "chunk_id": "chunk-1",
                            "positive_judgment_ids": ["missing-id"],
                        }
                    ]
                },
                {
                    "results": [
                        {
                            "section": "7",
                            "chunk_id": "chunk-1",
                            "positive_judgment_ids": [pair_by_doc["A"]["judgment_id"]],
                        }
                    ]
                },
                {"results": [{"judgment_id": pair_by_doc["A"]["judgment_id"], "relevance": 3, "agrees": True}]},
            ]
        )
        service = GroundTruthService(
            EvaluationConfig(
                model="deployment",
                modes=("hybrid",),
                llm_retries=1,
                batch_delay_seconds=0,
            ),
            client,
            "positive judge prompt",
            "verify prompt",
            sleep=lambda _: None,
        )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            resume_state_path = base / "resume_state.json"
            service.judge(pools, resume_state_path)
            judgments = json.loads(resume_state_path.read_text(encoding="utf-8"))["judgments"]

        self.assertEqual(len(judgments), 1)
        self.assertEqual(judgments[0]["judgment_id"], pair_by_doc["A"]["judgment_id"])
        self.assertEqual(len(client.calls), 3)

    def test_parallel_service_preserves_output_order(self) -> None:
        candidates = [_candidate(f"DOC-{index}", 1.0) for index in range(4)]
        pools = build_candidate_pool(
            itb_rows={"7:chunk-1": {"Chunk Text": "Cooling water requirement"}},
            records_by_source={("7", "hybrid"): [_matching_record("chunk-1", candidates)]},
        )
        pairs = iter_judge_pairs(pools)
        service = GroundTruthService(
            EvaluationConfig(
                model="deployment",
                modes=("hybrid",),
                max_concurrency=2,
                batch_delay_seconds=0,
            ),
            _EchoChatClient(),
            "judge prompt",
            "verify prompt",
            sleep=lambda _: None,
        )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            resume_state_path = base / "resume_state.json"
            service.judge(pools, resume_state_path)
            resume_state = json.loads(resume_state_path.read_text(encoding="utf-8"))
            judgments = resume_state["judgments"]
            verifications = resume_state["verifications"]

        self.assertEqual([row["judgment_id"] for row in judgments], [pair["judgment_id"] for pair in pairs])
        self.assertEqual([row["judgment_id"] for row in verifications], [pair["judgment_id"] for pair in pairs])

    def test_verified_positive_ground_truth_keeps_only_clear_verified_positives(self) -> None:
        judgments = [
            {
                "judgment_id": "positive",
                "section": "7",
                "chunk_id": "C",
                "mdl_doc_id": "A",
                "relevance": 3,
            },
            {
                "judgment_id": "negative",
                "section": "7",
                "chunk_id": "C",
                "mdl_doc_id": "B",
                "relevance": 0,
            },
            {
                "judgment_id": "weak",
                "section": "7",
                "chunk_id": "C",
                "mdl_doc_id": "C",
                "relevance": 2,
            },
            {
                "judgment_id": "disagreement",
                "section": "7",
                "chunk_id": "C",
                "mdl_doc_id": "D",
                "relevance": 2,
            },
        ]
        verifications = [
            {"judgment_id": "positive", "relevance": 3, "agrees": True},
            {"judgment_id": "negative", "relevance": 0, "agrees": True},
            {"judgment_id": "weak", "relevance": 2, "agrees": True},
            {"judgment_id": "disagreement", "relevance": 1, "agrees": True},
        ]

        rows = build_verified_positive_ground_truth_rows(judgments, verifications)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mdl_doc_id"], "A")
        self.assertEqual(rows[0]["label_status"], "positive")

    def test_resolved_positive_judgments_keep_only_selected_known_ids(self) -> None:
        pair = {
            "judgment_id": "6:chunk-1:A",
            "section": "6",
            "chunk_id": "chunk-1",
            "mdl": {"doc_id": "A"},
        }

        result = _resolve_positive_judgments(
            [pair],
            [
                {
                    "positive_judgment_ids": [pair["judgment_id"], pair["judgment_id"]],
                    "reasons": {pair["judgment_id"]: "Direct match."},
                }
            ],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["relevance"], 3)
        self.assertEqual(result[0]["reason"], "Direct match.")

    def test_resolved_verifications_clamp_scores_and_require_boolean_agreement(self) -> None:
        result = _resolve_verifications(
            [{"judgment_id": "6:chunk-1:A"}],
            [{"judgment_id": "6:chunk-1:A", "relevance": 9, "confidence": -1, "agrees": "true"}],
        )[0]

        self.assertEqual(result["relevance"], 3)
        self.assertNotIn("confidence", result)
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


class _EchoChatClient:
    def __init__(self) -> None:
        self.calls = []
        self.chat = _EchoChat(self)


class _EchoChat:
    def __init__(self, client: _EchoChatClient) -> None:
        self.completions = _EchoCompletions(client)


class _EchoCompletions:
    def __init__(self, client: _EchoChatClient) -> None:
        self.client = client

    def create(self, **parameters):
        self.client.calls.append(parameters)
        payload = json.loads(parameters["messages"][1]["content"])
        results = []
        for pool in payload.get("pools", []):
            results.append(
                {
                    "section": pool["section"],
                    "chunk_id": pool["chunk_id"],
                    "positive_judgment_ids": [candidate["judgment_id"] for candidate in pool["candidates"]],
                }
            )
        for judgment in payload.get("judgments", []):
            results.append(
                {
                    "judgment_id": judgment["judgment_id"],
                    "relevance": judgment["proposed_judgment"]["relevance"],
                    "agrees": True,
                }
            )
        for pool in payload.get("verification_pools", []):
            for candidate in pool.get("positive_candidates", []):
                results.append(
                    {
                        "judgment_id": candidate["judgment_id"],
                        "relevance": candidate["proposed_judgment"]["relevance"],
                        "agrees": True,
                    }
                )
        message = type("Message", (), {"content": json.dumps({"results": results})})()
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


def _candidate(
    doc_id: str,
    score: float,
    source_file: str = "",
    document_no: str = "",
    title: str | None = None,
) -> dict:
    return {
        "doc_id": doc_id,
        "source_file": source_file,
        "document_no": document_no,
        "title": title or f"Document {doc_id}",
        "equipment": "Steam Turbine",
        "deliverable": "Design Criteria",
        "text_content": f"Full text for {doc_id}",
        "embedding": [1.0, 0.0],
        "cross_encoder_score": score,
    }


def _judgment(pair: dict, relevance: int, confidence: float) -> dict:
    return {
        "judgment_id": pair["judgment_id"],
        "section": pair["section"],
        "chunk_id": pair["chunk_id"],
        "mdl_doc_id": pair["mdl"]["doc_id"],
        "relevance": relevance,
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    import csv

    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
