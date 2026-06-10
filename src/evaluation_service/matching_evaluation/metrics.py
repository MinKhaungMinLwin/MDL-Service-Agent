"""Compute matching quality metrics from graded relevance judgments."""

from __future__ import annotations

from statistics import mean

from evaluation_service.matching_evaluation.loaders import Qrels, Rankings

RELEVANCE_THRESHOLD = 3


def evaluate_cross_encoder(qrels: Qrels, rankings: Rankings, k: int = 20) -> tuple[dict, list[dict]]:
    """Evaluate final top matches after cross-encoder reranking."""
    recall_metric = f"recall_at_{k}"
    hit_rate_metric = f"hit_rate_at_{k}"
    rows = []
    for query_id in sorted(set(qrels) | set(rankings)):
        query_qrels = qrels.get(query_id, {})
        ranking = rankings.get(query_id, [])
        rows.append(
            {
                "query_id": query_id,
                recall_metric: _recall_at_k(query_qrels, ranking, k, RELEVANCE_THRESHOLD),
                hit_rate_metric: _hit_rate_at_k(query_qrels, ranking, k, RELEVANCE_THRESHOLD),
            }
        )
    return _summarize(rows, recall_metric), rows


def evaluate_retrieval(qrels: Qrels, rankings: Rankings, k: int = 100) -> tuple[dict, list[dict]]:
    """Evaluate candidate retrieval before cross-encoder reranking."""
    recall_metric = f"recall_at_{k}"
    rows = []
    for query_id in sorted(set(qrels) | set(rankings)):
        query_qrels = qrels.get(query_id, {})
        ranking = rankings.get(query_id, [])
        rows.append(
            {
                "query_id": query_id,
                recall_metric: _recall_at_k(query_qrels, ranking, k, RELEVANCE_THRESHOLD),
            }
        )
    return _summarize(rows, recall_metric), rows


def _summarize(rows: list[dict], recall_metric: str) -> dict:
    positive_queries = sum(row[recall_metric] is not None for row in rows)
    summary = {
        "queries": len(rows),
        "positive_queries": positive_queries,
    }
    metric_names = sorted({key for row in rows for key in row if key != "query_id"})
    for metric_name in metric_names:
        values = [row[metric_name] for row in rows if row.get(metric_name) is not None]
        summary[metric_name] = mean(values) if values else None
    return summary


def _recall_at_k(qrels: dict[str, int], ranking: list[str], k: int, threshold: int) -> float | None:
    relevant_doc_ids = {doc_id for doc_id, relevance in qrels.items() if relevance >= threshold}
    if not relevant_doc_ids:
        return None
    return len(relevant_doc_ids.intersection(ranking[:k])) / len(relevant_doc_ids)


def _hit_rate_at_k(qrels: dict[str, int], ranking: list[str], k: int, threshold: int) -> float | None:
    relevant_doc_ids = {doc_id for doc_id, relevance in qrels.items() if relevance >= threshold}
    if not relevant_doc_ids:
        return None
    return 1.0 if relevant_doc_ids.intersection(ranking[:k]) else 0.0
