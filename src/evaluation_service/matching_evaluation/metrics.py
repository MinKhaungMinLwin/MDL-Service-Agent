"""Compute matching quality metrics from graded relevance judgments."""

from __future__ import annotations

import math
from statistics import mean
from typing import Any

from evaluation_service.matching_evaluation.loaders import Qrels, Rankings

STRONG_RELEVANCE = 3


def evaluate_cross_encoder(qrels: Qrels, rankings: Rankings) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate final top matches after cross-encoder reranking."""
    rows = []
    for query_id in sorted(qrels):
        query_qrels = qrels[query_id]
        ranking = rankings.get(query_id, [])
        rows.append(
            {
                "query_id": query_id,
                "ndcg_at_10": _ndcg_at_k(query_qrels, ranking, 10),
                "recall_strong_at_20": _recall_at_k(query_qrels, ranking, 20, STRONG_RELEVANCE),
                "precision_strong_at_5": _precision_at_k(query_qrels, ranking, 5, STRONG_RELEVANCE),
                "success_strong_at_5": _success_at_k(query_qrels, ranking, 5, STRONG_RELEVANCE),
                "judged_at_20": _judged_at_k(query_qrels, ranking, 20),
            }
        )
    return _summarize(rows), rows


def evaluate_retrieval(qrels: Qrels, rankings: Rankings) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate candidate retrieval before cross-encoder reranking."""
    rows = []
    for query_id in sorted(qrels):
        query_qrels = qrels[query_id]
        ranking = rankings.get(query_id, [])
        rows.append(
            {
                "query_id": query_id,
                "recall_strong_at_100": _recall_at_k(query_qrels, ranking, 100, STRONG_RELEVANCE),
                "judged_at_100": _judged_at_k(query_qrels, ranking, 100),
            }
        )
    return _summarize(rows), rows


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"query_count": len(rows)}
    metric_names = sorted({key for row in rows for key in row if key != "query_id"})
    for metric_name in metric_names:
        values = [row[metric_name] for row in rows if row.get(metric_name) is not None]
        summary[metric_name] = mean(values) if values else None
        summary[f"{metric_name}_query_count"] = len(values)
    return summary


def _ndcg_at_k(qrels: dict[str, int], ranking: list[str], k: int) -> float | None:
    ideal_relevances = sorted(qrels.values(), reverse=True)[:k]
    ideal_dcg = _dcg(ideal_relevances)
    if ideal_dcg == 0:
        return None
    return _dcg([qrels.get(doc_id, 0) for doc_id in ranking[:k]]) / ideal_dcg


def _dcg(relevances: list[int]) -> float:
    return sum((2**relevance - 1) / math.log2(rank + 1) for rank, relevance in enumerate(relevances, start=1))


def _recall_at_k(qrels: dict[str, int], ranking: list[str], k: int, threshold: int) -> float | None:
    relevant_doc_ids = {doc_id for doc_id, relevance in qrels.items() if relevance >= threshold}
    if not relevant_doc_ids:
        return None
    return len(relevant_doc_ids.intersection(ranking[:k])) / len(relevant_doc_ids)


def _precision_at_k(qrels: dict[str, int], ranking: list[str], k: int, threshold: int) -> float:
    return sum(qrels.get(doc_id, 0) >= threshold for doc_id in ranking[:k]) / k


def _success_at_k(qrels: dict[str, int], ranking: list[str], k: int, threshold: int) -> float | None:
    if not any(relevance >= threshold for relevance in qrels.values()):
        return None
    return float(any(qrels.get(doc_id, 0) >= threshold for doc_id in ranking[:k]))


def _judged_at_k(qrels: dict[str, int], ranking: list[str], k: int) -> float | None:
    returned_doc_ids = ranking[:k]
    if not returned_doc_ids:
        return None
    return sum(doc_id in qrels for doc_id in returned_doc_ids) / len(returned_doc_ids)
