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
    build_reference_candidate_pool,
    build_reference_search_candidate_pool,
    iter_judge_pairs,
    limit_itb_rows,
    load_reference_mdl_candidates,
    write_high_precision_ground_truth,
)


class EvaluationServiceTest(unittest.TestCase):
    def test_cli_discovers_available_extract_sections_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "output_itb_section10_focused.csv").write_text("Chunk ID,Chunk Text\n", encoding="utf-8")
            (base / "output_itb_section2_focused.csv").write_text("Chunk ID,Chunk Text\n", encoding="utf-8")
            (base / "output_itb_sectionA_focused.csv").write_text("Chunk ID,Chunk Text\n", encoding="utf-8")

            self.assertEqual(_discover_sections(base), ("2", "10", "A"))

    def test_reference_pool_top_k_cannot_exceed_retrieval_candidates(self) -> None:
        with self.assertRaisesRegex(ValueError, "reference_pool_top_k cannot exceed"):
            EvaluationConfig(
                model="deployment",
                reference_retrieval_candidate_limit=10,
                reference_pool_top_k=20,
            )

    def test_max_itb_chunks_cannot_be_negative(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_itb_chunks cannot be negative"):
            EvaluationConfig(model="deployment", max_itb_chunks=-1)

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
            top_k=2,
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
            top_k=2,
        )

        self.assertEqual(len(pools[0]["candidates"]), 1)
        self.assertEqual(pools[0]["candidates"][0]["doc_id"], "A-1")

    def test_reference_pool_loads_and_deduplicates_reference_mdl_candidates(self) -> None:
        conn = _Neo4jConn(
            [
                _candidate("A-1", 1.0, source_file="R&N_MDL.xlsx", document_no="001", title="Layout"),
                _candidate("A-2", 0.9, source_file="R&N_MDL.xlsx", document_no="001", title="Layout"),
                _candidate("B", 0.8, source_file="R&N_MDL.xlsx", document_no="002", title="Foundation"),
            ]
        )
        candidates = load_reference_mdl_candidates(conn, "R&N_MDL.xlsx")
        pools = build_reference_candidate_pool(
            {"7:chunk-1": {"Chunk Text": "Cooling water requirement"}},
            candidates,
        )
        pairs = iter_judge_pairs(pools)

        self.assertEqual([candidate["doc_id"] for candidate in candidates], ["A-1", "B"])
        self.assertEqual(len(pools), 1)
        self.assertEqual({pair["mdl"]["source_file"] for pair in pairs}, {"R&N_MDL.xlsx"})
        self.assertEqual({pair["mdl"]["document_no"] for pair in pairs}, {"001", "002"})

    def test_reference_pool_uses_minimal_source_grounded_itb_fields(self) -> None:
        pools = build_reference_candidate_pool(
            {
                "7:chunk-1": {
                    "Document": "R&N_ITB",
                    "Chunk ID": "chunk-1",
                    "Page": "120",
                    "Section": "7",
                    "Section Path": "Section > Generated path",
                    "Hierarchy Context": "7. Mechanical requirements",
                    "1st Depth": "Mechanical",
                    "2nd Depth": "Cooling Water",
                    "Keywords": "cooling water, pump",
                    "Search Query": "cooling water pump generated query",
                    "Chunk Text": "Cooling water pump requirement",
                }
            },
            [_candidate("A", 1.0, source_file="R&N_MDL.xlsx", document_no="001", title="Pump")],
        )

        itb = pools[0]["itb"]
        self.assertEqual(
            itb,
            {
                "document": "R&N_ITB",
                "chunk_id": "chunk-1",
                "page": "120",
                "section": "7",
                "hierarchy_context": "7. Mechanical requirements",
                "depths": {"1st Depth": "Mechanical", "2nd Depth": "Cooling Water"},
                "keywords": "cooling water, pump",
                "chunk_text": "Cooling water pump requirement",
            },
        )
        self.assertNotIn("section_path", itb)
        self.assertNotIn("search_query", itb)

    def test_reference_pool_fails_when_neo4j_source_has_no_candidates(self) -> None:
        with self.assertRaisesRegex(ValueError, "No MDL candidates found"):
            load_reference_mdl_candidates(_Neo4jConn([]), "R&N_MDL.xlsx")

    def test_reference_search_pool_uses_matching_search_inside_reference_source(self) -> None:
        conn = _Neo4jConn(
            [
                _candidate("A", 1.0, source_file="R&N_MDL.xlsx", document_no="001", title="Pump"),
                _candidate("B", 0.9, source_file="R&N_MDL.xlsx", document_no="002", title="Valve"),
            ]
        )
        pools = build_reference_search_candidate_pool(
            {
                "7:chunk-1": {
                    "Document": "R&N_ITB",
                    "Page": "120",
                    "Section": "7",
                    "Hierarchy Context": "7. Mechanical requirements",
                    "1st Depth": "Mechanical",
                    "2nd Depth": "Cooling Water",
                    "Keywords": "cooling water, pump",
                    "Chunk Text": "Cooling water pump requirement",
                }
            },
            conn,
            EvaluationConfig(
                model="pool-only",
                modes=("keyword",),
                reference_retrieval_candidate_limit=2,
                reference_pool_top_k=1,
            ),
            "R&N_MDL.xlsx",
            "TestMDLDocument",
            cross_encoder_reranker=_RecordingReferenceReranker(),
        )

        self.assertEqual(len(pools), 1)
        self.assertEqual([candidate["doc_id"] for candidate in pools[0]["candidates"]], ["B"])
        self.assertNotIn("source_modes", pools[0]["candidates"][0])
        self.assertNotIn("cross_encoder_score", pools[0]["candidates"][0])
        self.assertEqual(conn.last_parameters["included_source_text"], "R&N_MDL.xlsx")
        self.assertEqual(conn.last_parameters["excluded_source_text"], "")

    def test_service_judges_all_rows_and_verifies_all_rows(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"6:chunk-1": {"Chunk Text": "Steam turbine foundation requirement"}},
            records_by_source={
                ("6", "hybrid"): [_matching_record("chunk-1", [_candidate("A", 1.0), _candidate("B", 0.5)])],
            },
            top_k=2,
        )
        pair_by_doc = {pair["mdl"]["doc_id"]: pair for pair in iter_judge_pairs(pools)}
        client = _ChatClient(
            [
                {
                    "results": [
                        _judgment(pair_by_doc["A"], relevance=0, confidence=0.95),
                        _judgment(pair_by_doc["B"], relevance=2, confidence=0.9),
                    ]
                },
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
            resume_state_path = base / "resume_state.json"
            service.judge_to_files(
                pools,
                resume_state_path,
                base / "ground_truth.csv",
            )
            resume_state = json.loads(resume_state_path.read_text(encoding="utf-8"))
            judgments = resume_state["judgments"]
            verifications = resume_state["verifications"]

        self.assertEqual(len(judgments), 2)
        self.assertEqual([call["messages"][0]["content"] for call in client.calls], ["judge prompt", "verify prompt"])
        judge_payload = json.loads(client.calls[0]["messages"][1]["content"])
        self.assertEqual(len(judge_payload["pools"]), 1)
        self.assertEqual(len(judge_payload["pools"][0]["candidates"]), 2)
        self.assertEqual(
            {candidate["judgment_id"] for candidate in judge_payload["pools"][0]["candidates"]},
            {pair_by_doc["A"]["judgment_id"], pair_by_doc["B"]["judgment_id"]},
        )
        self.assertEqual(
            {row["judgment_id"] for row in verifications},
            {pair_by_doc["A"]["judgment_id"], pair_by_doc["B"]["judgment_id"]},
        )

    def test_service_can_write_only_final_positive_and_negative_outputs(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"7:chunk-1": {"Chunk Text": "Cooling water requirement"}},
            records_by_source={("7", "hybrid"): [_matching_record("chunk-1", [_candidate("A", 1.0)])]},
            top_k=1,
        )
        pair = iter_judge_pairs(pools)[0]
        client = _ChatClient(
            [
                {"results": [_judgment(pair, relevance=3, confidence=0.95)]},
                {
                    "results": [
                        {
                            "judgment_id": pair["judgment_id"],
                            "relevance": 3,
                            "confidence": 0.95,
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
            positive_path = base / "ground_truth_positive.csv"
            negative_path = base / "ground_truth_negative.csv"
            service.judge_to_files(
                pools,
                resume_state_path=None,
                ground_truth_path=None,
                positive_path=positive_path,
                negative_path=negative_path,
            )

            self.assertTrue(positive_path.exists())
            self.assertTrue(negative_path.exists())
            self.assertFalse((base / "judgments.json").exists())
            self.assertFalse((base / "resume_state.json").exists())
            self.assertFalse((base / "ground_truth.csv").exists())

    def test_service_can_resume_existing_judgments(self) -> None:
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
            ]
        )
        service = GroundTruthService(
            EvaluationConfig(model="deployment", modes=("hybrid",), resume=True, batch_delay_seconds=0),
            client,
            "judge prompt",
            sleep=lambda _: None,
        )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            resume_state_path = base / "resume_state.json"
            resume_state_path.write_text(
                json.dumps({"judgments": [existing_judgment], "verifications": []}),
                encoding="utf-8",
            )
            service.judge_to_files(
                pools,
                resume_state_path,
                base / "ground_truth.csv",
            )
            judgments = json.loads(resume_state_path.read_text(encoding="utf-8"))["judgments"]

        self.assertEqual(len(judgments), 2)
        self.assertEqual(len(client.calls), 1)
        judge_payload = json.loads(client.calls[0]["messages"][1]["content"])
        self.assertEqual(len(judge_payload["pools"][0]["candidates"]), 1)
        self.assertEqual(
            judge_payload["pools"][0]["candidates"][0]["judgment_id"],
            pair_by_doc["B"]["judgment_id"],
        )

    def test_service_splits_large_candidate_pools(self) -> None:
        candidates = [_candidate(f"DOC-{index}", 1.0) for index in range(26)]
        pools = build_candidate_pool(
            itb_rows={"7:chunk-1": {"Chunk Text": "Cooling water requirement"}},
            records_by_source={("7", "hybrid"): [_matching_record("chunk-1", candidates)]},
            top_k=26,
        )
        pairs = iter_judge_pairs(pools)
        pair_by_id = {pair["judgment_id"]: pair for pair in pairs}
        client = _ChatClient(
            [
                {
                    "results": [
                        _judgment(pair_by_id[pair["judgment_id"]], relevance=1, confidence=0.8)
                        for pair in pairs[:25]
                    ]
                },
                {
                    "results": [
                        _judgment(pair_by_id[pair["judgment_id"]], relevance=1, confidence=0.8)
                        for pair in pairs[25:]
                    ]
                },
            ]
        )
        service = GroundTruthService(
            EvaluationConfig(
                model="deployment",
                modes=("hybrid",),
                judge_candidates_per_call=25,
                batch_delay_seconds=0,
            ),
            client,
            "judge prompt",
            sleep=lambda _: None,
        )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            resume_state_path = base / "resume_state.json"
            service.judge_to_files(
                pools,
                resume_state_path,
                base / "ground_truth.csv",
            )
            judgments = json.loads(resume_state_path.read_text(encoding="utf-8"))["judgments"]

        self.assertEqual(len(judgments), 26)
        self.assertEqual(len(client.calls), 2)
        payloads = [json.loads(call["messages"][1]["content"]) for call in client.calls]
        self.assertEqual([len(payload["pools"][0]["candidates"]) for payload in payloads], [25, 1])

    def test_service_retries_when_llm_omits_a_judgment(self) -> None:
        pools = build_candidate_pool(
            itb_rows={"7:chunk-1": {"Chunk Text": "Cooling water requirement"}},
            records_by_source={
                ("7", "hybrid"): [_matching_record("chunk-1", [_candidate("A", 1.0), _candidate("B", 0.5)])],
            },
            top_k=2,
        )
        pair_by_doc = {pair["mdl"]["doc_id"]: pair for pair in iter_judge_pairs(pools)}
        client = _ChatClient(
            [
                {"results": [_judgment(pair_by_doc["A"], relevance=1, confidence=0.8)]},
                {
                    "results": [
                        _judgment(pair_by_doc["A"], relevance=1, confidence=0.8),
                        _judgment(pair_by_doc["B"], relevance=2, confidence=0.9),
                    ]
                },
            ]
        )
        service = GroundTruthService(
            EvaluationConfig(model="deployment", modes=("hybrid",), llm_retries=1, batch_delay_seconds=0),
            client,
            "judge prompt",
            sleep=lambda _: None,
        )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            resume_state_path = base / "resume_state.json"
            service.judge_to_files(
                pools,
                resume_state_path,
                base / "ground_truth.csv",
            )
            judgments = json.loads(resume_state_path.read_text(encoding="utf-8"))["judgments"]

        self.assertEqual(len(judgments), 2)
        self.assertEqual(len(client.calls), 2)

    def test_parallel_service_preserves_output_order(self) -> None:
        candidates = [_candidate(f"DOC-{index}", 1.0) for index in range(4)]
        pools = build_candidate_pool(
            itb_rows={"7:chunk-1": {"Chunk Text": "Cooling water requirement"}},
            records_by_source={("7", "hybrid"): [_matching_record("chunk-1", candidates)]},
            top_k=4,
        )
        pairs = iter_judge_pairs(pools)
        service = GroundTruthService(
            EvaluationConfig(
                model="deployment",
                modes=("hybrid",),
                verify=True,
                batch_size=1,
                judge_candidates_per_call=1,
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
            service.judge_to_files(
                pools,
                resume_state_path,
                base / "ground_truth.csv",
            )
            resume_state = json.loads(resume_state_path.read_text(encoding="utf-8"))
            judgments = resume_state["judgments"]
            verifications = resume_state["verifications"]

        self.assertEqual([row["judgment_id"] for row in judgments], [pair["judgment_id"] for pair in pairs])
        self.assertEqual([row["judgment_id"] for row in verifications], [pair["judgment_id"] for pair in pairs])

    def test_high_precision_ground_truth_keeps_only_clear_verified_labels(self) -> None:
        judgments = [
            {
                "judgment_id": "positive",
                "section": "7",
                "chunk_id": "C",
                "mdl_doc_id": "A",
                "relevance": 3,
                "confidence": 0.9,
            },
            {
                "judgment_id": "negative",
                "section": "7",
                "chunk_id": "C",
                "mdl_doc_id": "B",
                "relevance": 0,
                "confidence": 0.2,
            },
            {
                "judgment_id": "weak",
                "section": "7",
                "chunk_id": "C",
                "mdl_doc_id": "C",
                "relevance": 2,
                "confidence": 0.9,
            },
            {
                "judgment_id": "disagreement",
                "section": "7",
                "chunk_id": "C",
                "mdl_doc_id": "D",
                "relevance": 2,
                "confidence": 0.9,
            },
        ]
        verifications = [
            {"judgment_id": "positive", "relevance": 3, "confidence": 0.9, "agrees": True},
            {"judgment_id": "negative", "relevance": 0, "confidence": 0.2, "agrees": True},
            {"judgment_id": "weak", "relevance": 2, "confidence": 0.9, "agrees": True},
            {"judgment_id": "disagreement", "relevance": 1, "confidence": 0.9, "agrees": True},
        ]

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            positive_path = base / "ground_truth_positive.csv"
            negative_path = base / "ground_truth_negative.csv"
            write_high_precision_ground_truth(positive_path, negative_path, judgments, verifications)
            positive_rows = positive_path.read_text(encoding="utf-8-sig").splitlines()
            negative_rows = negative_path.read_text(encoding="utf-8-sig").splitlines()

        self.assertEqual(len(positive_rows), 2)
        self.assertEqual(len(negative_rows), 3)
        self.assertIn(",3,0.9,positive", positive_rows[1])
        self.assertIn(",0,0.2,negative", negative_rows[1])
        self.assertIn(",2,0.9,negative", negative_rows[2])

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


class _Neo4jConn:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.last_parameters = {}

    def session(self):
        return _Neo4jSession(self)


class _Neo4jSession:
    def __init__(self, conn: _Neo4jConn) -> None:
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def run(self, query, **parameters):
        self.conn.last_parameters = parameters
        limit = parameters.get("limit")
        if isinstance(limit, int) and limit > 0:
            return self.conn.records[:limit]
        return self.conn.records


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
            for candidate in pool["candidates"]:
                results.append(
                    {
                        "judgment_id": candidate["judgment_id"],
                        "section": pool["section"],
                        "chunk_id": pool["chunk_id"],
                        "mdl_doc_id": candidate["mdl"]["doc_id"],
                        "relevance": 1,
                        "confidence": 0.8,
                    }
                )
        for judgment in payload.get("judgments", []):
            results.append(
                {
                    "judgment_id": judgment["judgment_id"],
                    "relevance": judgment["proposed_judgment"]["relevance"],
                    "confidence": 0.8,
                    "agrees": True,
                }
            )
        message = type("Message", (), {"content": json.dumps({"results": results})})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class _RecordingReferenceReranker:
    def rerank(self, query_text: str, candidates: list[dict], top_k: int) -> list[dict]:
        reranked = []
        for index, candidate in enumerate(reversed(candidates), start=1):
            reranked.append({**candidate, "cross_encoder_score": float(3 - index), "final_rank": index})
        return reranked[:top_k]


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
        "confidence": confidence,
    }


if __name__ == "__main__":
    unittest.main()
