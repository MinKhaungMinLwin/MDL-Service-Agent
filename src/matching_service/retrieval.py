"""Two-stage depth filtering and keyword-based candidate ranking."""

from __future__ import annotations

import math
import re

from matching_service.models import Candidate, MatchingConfig, RetrievalResult, candidate_key
from matching_service.query import unique_preserve_order
from matching_service.repository import MDLSearchRepository


class DepthRetriever:
    """Filter MDL candidates by ITB depth, then rank that pool by ITB keywords."""

    def __init__(self, repository: MDLSearchRepository, config: MatchingConfig) -> None:
        self.repository = repository
        self.config = config

    def retrieve(
        self,
        depth_filter_query: str,
        keyword_terms: list[str],
        keyword_embeddings: list[tuple[str, list[float]]],
    ) -> RetrievalResult:
        """Run depth keyword filtering, then keyword, semantic, or hybrid ranking."""
        depth_candidates = self.repository.search_keyword(depth_filter_query)
        keyword_candidates = self._rank_keyword_in_pool(depth_candidates, keyword_terms)
        semantic_candidates = []

        if self.config.retrieval_mode in {"semantic", "hybrid"}:
            semantic_candidates = self._rank_semantic_in_pool(depth_candidates, keyword_embeddings)

        if self.config.retrieval_mode == "keyword":
            candidates = _sort_single_retrieval(keyword_candidates)
        elif self.config.retrieval_mode == "semantic":
            candidates = _sort_single_retrieval(semantic_candidates or depth_candidates)
        else:
            candidates = _merge_hybrid_candidates(keyword_candidates, semantic_candidates, self.config.rrf_k)

        return RetrievalResult(candidates, keyword_candidates, semantic_candidates)

    def _rank_keyword_in_pool(
        self,
        candidates: list[Candidate],
        keyword_terms: list[str],
    ) -> list[Candidate]:
        if not keyword_terms:
            return [dict(candidate) for candidate in candidates]

        ranked_candidates = []
        for candidate in candidates:
            ranked_candidate = dict(candidate)
            score, matched_terms = _keyword_score(candidate, keyword_terms)
            ranked_candidate["keyword_score"] = score
            ranked_candidate["matched_terms"] = matched_terms
            ranked_candidates.append(ranked_candidate)

        ranked_candidates.sort(
            key=lambda candidate: (
                candidate.get("keyword_score") or 0.0,
                candidate.get("bm25_score") or 0.0,
            ),
            reverse=True,
        )
        for rank, candidate in enumerate(ranked_candidates, start=1):
            candidate["bm25_rank"] = rank
            candidate["retrieval_rank"] = rank
        return ranked_candidates

    def _rank_semantic_in_pool(
        self,
        candidates: list[Candidate],
        keyword_embeddings: list[tuple[str, list[float]]],
    ) -> list[Candidate]:
        if not keyword_embeddings:
            return []

        ranked_candidates = []
        normalized_queries = [(term, _normalize_vector(embedding)) for term, embedding in keyword_embeddings]
        for candidate in candidates:
            embedding = candidate.get("embedding")
            if not embedding:
                continue
            normalized_candidate = _normalize_vector(embedding)
            scores = [
                (term, _dot(query_embedding, normalized_candidate))
                for term, query_embedding in normalized_queries
            ]
            best_score = max((score for _, score in scores), default=0.0)
            matched_terms = [term for term, score in scores if score == best_score]
            ranked_candidate = dict(candidate)
            ranked_candidate["semantic_score"] = best_score
            ranked_candidate["matched_terms"] = matched_terms
            ranked_candidates.append(ranked_candidate)

        ranked_candidates.sort(
            key=lambda candidate: (
                candidate.get("semantic_score") or 0.0,
                candidate.get("bm25_score") or 0.0,
            ),
            reverse=True,
        )
        for rank, candidate in enumerate(ranked_candidates, start=1):
            candidate["semantic_rank"] = rank
            candidate["retrieval_rank"] = rank
        return ranked_candidates


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


def _keyword_score(candidate: Candidate, keyword_terms: list[str]) -> tuple[float, list[str]]:
    candidate_text = _candidate_text(candidate)
    candidate_tokens = set(candidate_text.split())
    matched_terms = []
    score = 0.0
    for term in keyword_terms:
        normalized_term = _normalize_text(term)
        if not normalized_term:
            continue
        if normalized_term in candidate_text:
            matched_terms.append(term)
            score += 2.0 if " " in normalized_term else 1.0
            continue
        token_hits = sum(1 for token in normalized_term.split() if token in candidate_tokens)
        if token_hits:
            matched_terms.append(term)
            score += token_hits / max(len(normalized_term.split()), 1)
    return score, unique_preserve_order(matched_terms)


def _candidate_text(candidate: Candidate) -> str:
    values = [
        str(candidate.get(field) or "")
        for field in (
            "title",
            "equipment",
            "system",
            "building",
            "study_survey",
            "others",
            "deliverable",
            "text_content",
        )
    ]
    return _normalize_text(" ".join(values))


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=False))
