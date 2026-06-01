"""Depth-based keyword, semantic, and hybrid candidate retrieval."""

from __future__ import annotations

from matching_service.models import Candidate, MatchingConfig, RetrievalResult, candidate_key
from matching_service.query import unique_preserve_order
from matching_service.repository import MDLSearchRepository


class DepthRetriever:
    """Retrieve MDL candidates with ITB depth phrases."""

    def __init__(self, repository: MDLSearchRepository, config: MatchingConfig) -> None:
        self.repository = repository
        self.config = config

    def retrieve(
        self,
        depth_filter_query: str,
        depth_embeddings: list[tuple[str, list[float]]],
    ) -> RetrievalResult:
        """Retrieve and merge depth candidates with the configured search mode."""
        keyword_candidates = []
        semantic_candidates = []

        if self.config.retrieval_mode in {"keyword", "hybrid"}:
            keyword_candidates = self.repository.search_keyword(depth_filter_query)

        if self.config.retrieval_mode in {"semantic", "hybrid"}:
            semantic_candidates = self._search_semantic(depth_embeddings)

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

    def _search_semantic(
        self,
        depth_embeddings: list[tuple[str, list[float]]],
    ) -> list[Candidate]:
        term_candidates = []
        for term, embedding in depth_embeddings:
            term_candidates.extend(self.repository.search_semantic(embedding, term))
        return _merge_semantic_candidates(term_candidates)


def _merge_semantic_candidates(term_candidates: list[Candidate]) -> list[Candidate]:
    """Deduplicate per-term vector results and keep each document's best score."""
    merged: dict[str, Candidate] = {}
    for candidate in term_candidates:
        key = candidate_key(candidate)
        if key not in merged:
            merged[key] = dict(candidate)
            continue

        existing = merged[key]
        existing["matched_terms"] = unique_preserve_order(
            existing.get("matched_terms", []) + candidate.get("matched_terms", [])
        )
        if candidate.get("semantic_score", 0.0) > existing.get("semantic_score", 0.0):
            existing["semantic_score"] = candidate.get("semantic_score")

    ranked_candidates = sorted(
        merged.values(),
        key=lambda candidate: (
            candidate.get("semantic_score") or 0.0,
            len(candidate.get("matched_terms", [])),
        ),
        reverse=True,
    )
    for rank, candidate in enumerate(ranked_candidates, start=1):
        candidate["semantic_rank"] = rank
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
