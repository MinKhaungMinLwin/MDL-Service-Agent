"""Rank retrieved MDL document candidates."""

from __future__ import annotations

from typing import Any

from matching_service.models import Candidate


class CrossEncoderReranker:
    """Rerank retrieved candidates with a query-document relevance model."""

    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("Cross-encoder reranking requires sentence-transformers.") from exc

        self.model_name = model_name
        self.batch_size = batch_size
        self.model = CrossEncoder(model_name)

    def rerank(self, query_text: str, candidates: list[Candidate], top_k: int) -> list[Candidate]:
        """Score candidates in one batch and return the best matches."""
        if not query_text or not candidates:
            return []

        pairs = [(query_text, build_candidate_text(candidate)) for candidate in candidates]
        scores = self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)

        reranked_candidates = []
        for candidate, score in zip(candidates, scores, strict=True):
            reranked_candidate = dict(candidate)
            reranked_candidate["cross_encoder_score"] = float(score)
            reranked_candidates.append(reranked_candidate)

        reranked_candidates.sort(
            key=lambda candidate: (
                candidate["cross_encoder_score"],
                -(candidate.get("retrieval_rank") or len(candidates) + 1),
            ),
            reverse=True,
        )
        for rank, candidate in enumerate(reranked_candidates, start=1):
            candidate["final_rank"] = rank
        return reranked_candidates[:top_k]


def build_candidate_text(candidate: dict[str, Any]) -> str:
    """Build a compact MDL representation for relevance scoring."""
    fields = (
        ("Title", "title"),
        ("Equipment", "equipment"),
        ("System", "system"),
        ("Building", "building"),
        ("Study/Survey", "study_survey"),
        ("Others", "others"),
        ("Deliverable", "deliverable"),
        ("Text Content", "text_content"),
    )
    return "\n".join(
        f"{label}: {value}"
        for label, field in fields
        if (value := str(candidate.get(field) or "").strip())
    )
