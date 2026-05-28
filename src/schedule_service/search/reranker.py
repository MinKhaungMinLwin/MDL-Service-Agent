"""Reranking helpers."""

from __future__ import annotations

from schedule_service.models import Candidate, ScheduleActivity

DEFAULT_RRF_K = 60


def rank_desc(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)


def rrf_candidates(
    activities: list[ScheduleActivity],
    bm25_scores: list[float],
    semantic_scores: list[float],
    retrieve_k: int,
    top_k: int,
    has_semantic: bool,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[Candidate]:
    bm25_order = rank_desc(bm25_scores)
    bm25_ranks = {index: rank for rank, index in enumerate(bm25_order, start=1)}
    semantic_order = rank_desc(semantic_scores) if has_semantic else []
    semantic_ranks = {index: rank for rank, index in enumerate(semantic_order, start=1)}

    candidate_indexes = set(bm25_order[:retrieve_k])
    if has_semantic:
        candidate_indexes.update(semantic_order[:retrieve_k])

    candidates: list[Candidate] = []
    for index in candidate_indexes:
        bm25_rank = bm25_ranks.get(index)
        semantic_rank = semantic_ranks.get(index)
        rrf_score = 0.0
        if bm25_rank is not None:
            rrf_score += 1.0 / (rrf_k + bm25_rank)
        if semantic_rank is not None:
            rrf_score += 1.0 / (rrf_k + semantic_rank)
        candidates.append(
            Candidate(
                activity=activities[index],
                bm25_rank=bm25_rank,
                semantic_rank=semantic_rank,
                bm25_score=bm25_scores[index],
                semantic_score=semantic_scores[index],
                rrf_score=rrf_score,
            )
        )

    candidates.sort(key=lambda item: item.rrf_score, reverse=True)
    return candidates[:top_k]
