"""Depth-based keyword, semantic, and hybrid candidate retrieval."""

from __future__ import annotations

from matching_service.models import Candidate, MatchingConfig, RetrievalResult, candidate_key
from matching_service.repository import MDLSearchRepository


class DepthRetriever:
    """Retrieve MDL candidates with ITB depth phrases."""

    def __init__(self, repository: MDLSearchRepository, config: MatchingConfig) -> None:
        self.repository = repository
        self.config = config

    def retrieve(
        self,
        depth_filter_query: str,
        keyword_filter_query: str,
        semantic_query: str,
        semantic_embedding: list[float],
    ) -> RetrievalResult:
        """Retrieve and merge ITB candidates with the configured search mode."""
        keyword_candidates = []
        semantic_candidates = []

        if self.config.retrieval_mode in {"keyword", "hybrid"}:
            keyword_candidates = _merge_keyword_candidates(
                [
                    self.repository.search_keyword(query)
                    for query in (depth_filter_query, keyword_filter_query)
                    if query
                ],
                self.config.rrf_k,
            )

        if self.config.retrieval_mode in {"semantic", "hybrid"}:
            semantic_candidates = self.repository.search_semantic(semantic_embedding, semantic_query)

        if self.config.retrieval_mode == "keyword":
            candidates = _sort_single_retrieval(keyword_candidates)
        elif self.config.retrieval_mode == "semantic":
            candidates = _sort_single_retrieval(semantic_candidates)
        else:
            candidates = _merge_hybrid_candidates(keyword_candidates, semantic_candidates, self.config.rrf_k)

        return RetrievalResult(
            candidates[: self.config.retrieval_candidate_limit],
            keyword_candidates,
            semantic_candidates,
        )


def _merge_keyword_candidates(candidate_lists: list[list[Candidate]], rrf_k: int) -> list[Candidate]:
    """Merge depth and keyword full-text rankings with reciprocal rank fusion."""
    merged: dict[str, Candidate] = {}
    for candidates in candidate_lists:
        for rank, candidate in enumerate(candidates, start=1):
            key = candidate_key(candidate)
            if key not in merged:
                merged[key] = dict(candidate)
                merged[key]["keyword_rrf_score"] = 0.0
            existing = merged[key]
            existing["keyword_rrf_score"] += _rrf_score(rank, rrf_k=rrf_k)
            if candidate.get("bm25_score", 0.0) > existing.get("bm25_score", 0.0):
                existing["bm25_score"] = candidate.get("bm25_score")

    ranked_candidates = sorted(
        merged.values(),
        key=lambda candidate: (
            candidate.get("keyword_rrf_score") or 0.0,
            candidate.get("bm25_score") or 0.0,
        ),
        reverse=True,
    )
    for rank, candidate in enumerate(ranked_candidates, start=1):
        candidate["bm25_rank"] = rank
        candidate["retrieval_rank"] = rank
    return ranked_candidates


def _merge_hybrid_candidates(
    keyword_candidates: list[Candidate],
    semantic_candidates: list[Candidate],
    rrf_k: int,
) -> list[Candidate]:
    """Merge keyword and semantic rankings with reciprocal rank fusion."""
    merged = {candidate_key(candidate): dict(candidate) for candidate in keyword_candidates}
    for candidate in semantic_candidates:
        key = candidate_key(candidate)
        if key in merged:
            merged[key].update(
                {
                    "semantic_rank": candidate.get("semantic_rank"),
                    "semantic_score": candidate.get("semantic_score"),
                    "matched_terms": candidate.get("matched_terms", []),
                }
            )
        else:
            merged[key] = dict(candidate)

    for candidate in merged.values():
        candidate["rrf_score"] = _rrf_score(
            candidate.get("bm25_rank"),
            candidate.get("semantic_rank"),
            rrf_k=rrf_k,
        )

    ranked_candidates = sorted(
        merged.values(),
        key=lambda candidate: (
            candidate.get("rrf_score") or 0.0,
            candidate.get("bm25_score") or 0.0,
            candidate.get("semantic_score") or 0.0,
        ),
        reverse=True,
    )
    for rank, candidate in enumerate(ranked_candidates, start=1):
        candidate["retrieval_rank"] = rank
    return ranked_candidates


def _sort_single_retrieval(candidates: list[Candidate]) -> list[Candidate]:
    """Preserve a single search channel's existing ranking."""
    ranked_candidates = sorted(candidates, key=lambda candidate: candidate.get("retrieval_rank") or len(candidates) + 1)
    for rank, candidate in enumerate(ranked_candidates, start=1):
        candidate["retrieval_rank"] = rank
    return ranked_candidates


def _rrf_score(*ranks: int | None, rrf_k: int) -> float:
    return sum(1.0 / (rrf_k + rank) for rank in ranks if rank is not None)
