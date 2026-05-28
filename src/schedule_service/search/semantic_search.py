"""Semantic search utilities."""

from __future__ import annotations

import math
from pathlib import Path

from loguru import logger

from common.embedding_client import AzureEmbeddingService
from schedule_service.models import ScheduleActivity


class SemanticIndex:
    """In-memory cosine-similarity index for activity embeddings."""

    def __init__(self, embeddings: list[list[float]]) -> None:
        """Store normalized embeddings and create an embedding client."""
        self.embeddings = [_normalize_vector(embedding) for embedding in embeddings]
        self.embedding_service = AzureEmbeddingService()

    @classmethod
    def build(cls, activities: list[ScheduleActivity], cache_dir: Path) -> SemanticIndex:
        """Build a semantic index for schedule activities."""
        del cache_dir
        service = AzureEmbeddingService()
        target_texts = [activity.target_text for activity in activities]
        _log(f"Embedding {len(target_texts)} schedule activity target texts")
        embeddings = service.embed_texts(target_texts)
        return cls(embeddings)

    def score(self, query: str) -> list[float]:
        """Score indexed activities against a query embedding."""
        query_embedding = _normalize_vector(self.embedding_service.embed_text(query))
        return [_dot(query_embedding, embedding) for embedding in self.embeddings]


def _normalize_vector(vector: list[float]) -> list[float]:
    """Normalize a vector for cosine similarity."""
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _dot(left: list[float], right: list[float]) -> float:
    """Return the dot product of two equal-length vectors."""
    return sum(a * b for a, b in zip(left, right, strict=True))


def _log(message: str) -> None:
    """Log a semantic search message."""
    logger.info(message)
