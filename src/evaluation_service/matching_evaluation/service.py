"""Application service for ITB-to-MDL matching evaluation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from loguru import logger

from evaluation_service.matching_evaluation.loaders import load_matching_runs, load_qrels
from evaluation_service.matching_evaluation.metrics import (
    RELEVANCE_THRESHOLD,
    evaluate_cross_encoder,
    evaluate_retrieval,
)

SUMMARY_HEADER = [
    "mode",
    "stage",
    "queries",
    "positive_queries",
    "recall_at_20",
    "hit_rate_at_20",
    "recall_at_100",
]
QUERY_HEADER = [
    "mode",
    "stage",
    "query_id",
    "recall_at_20",
    "hit_rate_at_20",
    "recall_at_100",
]
REPORT_HEADER = [
    "ground_truth_path",
    "matching_dir",
    "modes",
    "sections",
    "queries",
    "relevance_threshold",
    "output_limit",
    "retrieval_limit",
    "skipped_stages",
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
        """Evaluate available ranking stages and write CSV reports."""
        qrels = load_qrels(ground_truth_path, sections)
        summaries = []
        query_metrics = []
        evaluated_query_ids = set()
        skipped_stages = []
        output_limit = None
        retrieval_limit = None
        for mode in modes:
            cross_encoder_rankings, retrieval_rankings, metadata = load_matching_runs(matching_dir, mode, sections)
            summary, rows = evaluate_cross_encoder(qrels, cross_encoder_rankings)
            summaries.append({"mode": mode, "stage": "cross_encoder", **summary})
            query_metrics.extend({"mode": mode, "stage": "cross_encoder", **row} for row in rows)
            evaluated_query_ids.update(row["query_id"] for row in rows)
            output_limit = _max_optional(output_limit, metadata.get("output_limit"))
            retrieval_limit = _max_optional(retrieval_limit, metadata.get("retrieval_limit"))

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
            evaluated_query_ids.update(row["query_id"] for row in rows)

        output_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(output_dir / "summary.csv", SUMMARY_HEADER, summaries)
        _write_csv(output_dir / "query_metrics.csv", QUERY_HEADER, query_metrics)
        _write_csv(
            output_dir / "report.csv",
            REPORT_HEADER,
            [
                {
                    "ground_truth_path": str(ground_truth_path),
                    "matching_dir": str(matching_dir),
                    "modes": ";".join(modes),
                    "sections": ";".join(sections),
                    "queries": len(evaluated_query_ids),
                    "relevance_threshold": RELEVANCE_THRESHOLD,
                    "output_limit": output_limit,
                    "retrieval_limit": retrieval_limit,
                    "skipped_stages": _format_skipped_stages(skipped_stages),
                }
            ],
        )
        logger.info("Saved matching evaluation reports: {}", output_dir)


def _write_csv(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _max_optional(left: int | None, right: Any) -> int | None:
    if right is None:
        return left
    return right if left is None else max(left, int(right))


def _format_skipped_stages(rows: list[dict[str, Any]]) -> str:
    return "; ".join(f"{row.get('mode', '')}/{row.get('stage', '')}: {row.get('reason', '')}" for row in rows)
