"""Focused tests for ITB-to-MDL matching evaluation."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from evaluation_service.matching_evaluation.loaders import load_matching_runs, load_qrels
from evaluation_service.matching_evaluation.metrics import evaluate_cross_encoder, evaluate_retrieval
from evaluation_service.matching_evaluation.service import MatchingEvaluationService


class MatchingEvaluationTest(unittest.TestCase):
    def test_loaders_read_qrels_and_both_matching_stages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ground_truth_path = base / "ground_truth.csv"
            matching_dir = base / "matching"
            _write_ground_truth(
                ground_truth_path,
                [
                    {"section": "7", "chunk_id": "chunk-1", "mdl_doc_id": "A", "relevance": "3"},
                    {"section": "6", "chunk_id": "chunk-2", "mdl_doc_id": "B", "relevance": "2"},
                ],
            )
            _write_matching_json(
                matching_dir / "hybrid" / "output_match_all_projects_section7.json",
                [
                    {
                        "chunk_id": "chunk-1",
                        "retrieval_candidates": [{"doc_id": "B"}, {"doc_id": "A"}],
                        "candidates": [{"doc_id": "A"}, {"doc_id": "B"}],
                    }
                ],
            )

            qrels = load_qrels(ground_truth_path, ("7",))
            cross_encoder, retrieval = load_matching_runs(matching_dir, "hybrid", ("7",))

        self.assertEqual(qrels, {"7:chunk-1": {"A": 3}})
        self.assertEqual(cross_encoder, {"7:chunk-1": ["A", "B"]})
        self.assertEqual(retrieval, {"7:chunk-1": ["B", "A"]})

    def test_cross_encoder_metrics_use_graded_relevance_and_skip_missing_positive_denominators(self) -> None:
        summary, rows = evaluate_cross_encoder(
            qrels={
                "7:chunk-1": {"A": 3, "B": 2, "C": 0},
                "7:chunk-2": {"D": 1},
            },
            rankings={
                "7:chunk-1": ["B", "A", "X", "C"],
                "7:chunk-2": ["D"],
            },
        )

        row_by_query = {row["query_id"]: row for row in rows}
        self.assertAlmostEqual(row_by_query["7:chunk-1"]["ndcg_at_20"], 0.8339912323981488)
        self.assertEqual(row_by_query["7:chunk-1"]["recall_at_20"], 1.0)
        self.assertEqual(row_by_query["7:chunk-1"]["judged_at_20"], 0.75)
        self.assertIsNone(row_by_query["7:chunk-2"]["recall_at_20"])
        self.assertEqual(summary["queries"], 2)
        self.assertEqual(summary["positive_queries"], 1)

    def test_retrieval_metrics_measure_recall_before_cross_encoder(self) -> None:
        summary, rows = evaluate_retrieval(
            qrels={
                "7:chunk-1": {"A": 3, "B": 0},
                "7:chunk-2": {"C": 2},
            },
            rankings={
                "7:chunk-1": ["B", "A"],
                "7:chunk-2": ["X", "C"],
            },
        )

        row_by_query = {row["query_id"]: row for row in rows}
        self.assertEqual(row_by_query["7:chunk-1"]["recall_at_100"], 1.0)
        self.assertIsNone(row_by_query["7:chunk-2"]["recall_at_100"])
        self.assertEqual(summary["recall_at_100"], 1.0)
        self.assertEqual(summary["judged_at_100"], 0.75)

    def test_service_writes_cross_encoder_report_and_skips_unavailable_legacy_retrieval_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ground_truth_path = base / "ground_truth.csv"
            matching_dir = base / "matching"
            output_dir = base / "evaluation"
            _write_ground_truth(
                ground_truth_path,
                [{"section": "7", "chunk_id": "chunk-1", "mdl_doc_id": "A", "relevance": "3"}],
            )
            _write_matching_json(
                matching_dir / "hybrid" / "output_match_all_projects_section7.json",
                [{"chunk_id": "chunk-1", "candidates": [{"doc_id": "A"}]}],
            )

            MatchingEvaluationService().evaluate(
                ground_truth_path=ground_truth_path,
                matching_dir=matching_dir,
                output_dir=output_dir,
                modes=("hybrid",),
                sections=("7",),
            )
            with open(output_dir / "summary.csv", encoding="utf-8-sig") as file:
                summary_rows = list(csv.DictReader(file))
            report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))

        self.assertEqual([(row["mode"], row["stage"]) for row in summary_rows], [("hybrid", "cross_encoder")])
        self.assertEqual(report["relevance_threshold"], 3)
        self.assertEqual(report["output_limit"], 20)
        self.assertEqual(report["retrieval_limit"], 100)
        self.assertEqual(report["skipped_stages"][0]["stage"], "retrieval")


def _write_ground_truth(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["section", "chunk_id", "mdl_doc_id", "relevance"])
        writer.writeheader()
        writer.writerows(rows)


def _write_matching_json(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
