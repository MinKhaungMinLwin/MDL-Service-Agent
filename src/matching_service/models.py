"""Shared models for ITB depth to MDL document matching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Candidate = dict[str, Any]


@dataclass(frozen=True)
class MatchingConfig:
    """Runtime configuration for depth-based MDL matching."""

    retrieval_mode: str = "keyword"
    retrieval_candidate_limit: int = 100
    output_limit: int = 20
    source_files: tuple[str, ...] = ()
    fulltext_index_name: str = "test_mdl_document_fulltext_idx"
    vector_index_name: str = "test_mdl_document_vector_idx"
    node_label: str = "TestMDLDocument"
    rrf_k: int = 60

    def __post_init__(self) -> None:
        if self.retrieval_mode not in {"keyword", "semantic", "hybrid"}:
            raise ValueError("retrieval_mode must be keyword, semantic, or hybrid")
        if self.retrieval_candidate_limit <= 0:
            raise ValueError("retrieval_candidate_limit must be positive")
        if self.output_limit <= 0:
            raise ValueError("output_limit must be positive")
        if self.output_limit > self.retrieval_candidate_limit:
            raise ValueError("output_limit cannot exceed retrieval_candidate_limit")
        if any(not source_file.strip() for source_file in self.source_files):
            raise ValueError("source_files cannot contain blank values")


@dataclass(frozen=True)
class RetrievalResult:
    """Candidates returned by one configured retrieval mode."""

    candidates: list[Candidate]
    keyword_candidates: list[Candidate]
    semantic_candidates: list[Candidate]


def candidate_key(candidate: Candidate) -> str:
    """Return a stable key for deduplicating MDL candidates."""
    doc_id = candidate.get("doc_id")
    if doc_id:
        return f"doc_id:{doc_id}"
    return "|".join(
        str(candidate.get(field, ""))
        for field in ("source_file", "document_no", "title")
    )
