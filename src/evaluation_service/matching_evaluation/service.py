"""Application service for ITB-to-MDL matching evaluation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from loguru import logger

from common.json_io import write_json
from evaluation_service.matching_evaluation.loaders import load_matching_runs, load_qrels
from evaluation_service.matching_evaluation.metrics import evaluate_cross_encoder, evaluate_retrieval

SUMMARY_HEADER = [
    "mode",
    "stage",
    "query_count",
    "ndcg_at_10",
    "ndcg_at_10_query_count",
    "recall_strong_at_20",
    "recall_strong_at_20_query_count",
    "precision_strong_at_5",
    "precision_strong_at_5_query_count",
    "success_strong_at_5",
    "success_strong_at_5_query_count",
    "judged_at_20",
    "judged_at_20_query_count",
    "recall_strong_at_100",
    "recall_strong_at_100_query_count",
    "judged_at_100",
    "judged_at_100_query_count",
]
QUERY_HEADER = [
    "mode",
    "stage",
    "query_id",
    "ndcg_at_10",
    "recall_strong_at_20",
    "precision_strong_at_5",
    "success_strong_at_5",
    "judged_at_20",
    "recall_strong_at_100",
    "judged_at_100",
]


class MatchingEvaluationService:
    """Evaluate matching artifacts against graded relevance judgments."""

    def evaluate(
        self,
        ground_truth_path: Path,
        matching_dir: Path,
        output_dir: Path,
        modes: tuple[str, ...],
        sections: tuple[str, ...],
    ) -> None:
        """Evaluate available ranking stages and write CSV/JSON reports."""
        qrels = load_qrels(ground_truth_path, sections)
        summaries = []
        query_metrics = []
        skipped_stages = []
        for mode in modes:
            cross_encoder_rankings, retrieval_rankings = load_matching_runs(matching_dir, mode, sections)
            summary, rows = evaluate_cross_encoder(qrels, cross_encoder_rankings)
            summaries.append({"mode": mode, "stage": "cross_encoder", **summary})
            query_metrics.extend({"mode": mode, "stage": "cross_encoder", **row} for row in rows)

            if retrieval_rankings is None:
                skipped_stages.append(
                    {
                        "mode": mode,
                        "stage": "retrieval",
                        "reason": "Matching artifacts do not contain retrieval_candidates. Run itb-match again.",
                    }
                )
                logger.warning(
                    "Skipping {} retrieval evaluation: run itb-match again to emit retrieval candidates",
                    mode,
                )
                continue
            summary, rows = evaluate_retrieval(qrels, retrieval_rankings)
            summaries.append({"mode": mode, "stage": "retrieval", **summary})
            query_metrics.extend({"mode": mode, "stage": "retrieval", **row} for row in rows)

        output_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(output_dir / "summary.csv", SUMMARY_HEADER, summaries)
        _write_csv(output_dir / "query_metrics.csv", QUERY_HEADER, query_metrics)
        write_json(
            output_dir / "report.json",
            {
                "ground_truth_path": str(ground_truth_path),
                "matching_dir": str(matching_dir),
                "modes": list(modes),
                "sections": list(sections),
                "qrel_query_count": len(qrels),
                "summaries": summaries,
                "skipped_stages": skipped_stages,
            },
        )
        logger.info("Saved matching evaluation reports: {}", output_dir)


def _write_csv(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
