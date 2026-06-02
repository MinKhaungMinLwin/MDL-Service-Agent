"""Semantic search utilities."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from loguru import logger

from common.embedding_client import AzureEmbeddingService
from schedule_service.models import ScheduleActivity

_CACHE_FILENAME = "activity_embeddings.json"


class SemanticIndex:
    """In-memory cosine-similarity index for activity embeddings (numpy-backed)."""

    def __init__(self, embeddings: list[list[float]]) -> None:
        """Normalize and store embeddings as a float32 matrix."""
        normalized = [_normalize_vector(e) for e in embeddings]
        # shape: (n_activities, embedding_dims)
        self.matrix = np.array(normalized, dtype=np.float32)
        self.embedding_service = AzureEmbeddingService()

    @classmethod
    def build(cls, activities: list[ScheduleActivity], cache_dir: Path) -> SemanticIndex:
        """Build (or load from cache) a semantic index for schedule activities.

        Cache is keyed by SHA-256 of all target texts and auto-invalidates when
        the schedule data changes.
        """
        service = AzureEmbeddingService()
        target_texts = [activity.target_text for activity in activities]

        key = _hash_texts(target_texts)
        cache_path = cache_dir / _CACHE_FILENAME

        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("key") == key:
                    _log(f"Activity semantic cache HIT ({len(activities)} activities)")
                    return cls(cached["embeddings"])
                _log("Activity semantic cache STALE — rebuilding")
            except Exception as exc:
                _log(f"Activity semantic cache unreadable ({exc}), rebuilding")

        _log(f"Embedding {len(target_texts)} schedule activity target texts")
        embeddings = service.embed_texts(target_texts)

        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"key": key, "embeddings": embeddings}, ensure_ascii=False),
            encoding="utf-8",
        )
        _log(f"Activity semantic index built and cached → {cache_path}")
        return cls(embeddings)

    def score(self, query: str) -> list[float]:
        """Score all activities against a query string (calls embedding API)."""
        raw = self.embedding_service.embed_text(query)
        q = np.array(_normalize_vector(raw), dtype=np.float32)
        return (self.matrix @ q).tolist()

    def score_embedding(self, query_embedding: list[float]) -> list[float]:
        """Score all activities against a pre-computed query embedding."""
        q = np.array(_normalize_vector(query_embedding), dtype=np.float32)
        return (self.matrix @ q).tolist()

    def score_matrix(self, query_embeddings: np.ndarray) -> np.ndarray:
        """Score all activities against multiple query embeddings in one matrix multiply.

        Args:
            query_embeddings: raw (unnormalized) embeddings, shape (n_queries, dims)
        Returns:
            cosine similarities, shape (n_queries, n_activities)
        """
        norms = np.linalg.norm(query_embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        q_norm = (query_embeddings / norms).astype(np.float32)
        return q_norm @ self.matrix.T


def _normalize_vector(vector: list[float]) -> list[float]:
    """Normalize a vector for cosine similarity."""
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _dot(left: list[float], right: list[float]) -> float:
    """Return the dot product of two equal-length vectors."""
    return sum(a * b for a, b in zip(left, right, strict=True))


def _hash_texts(texts: list[str]) -> str:
    combined = "\n".join(texts).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()[:16]


def _log(message: str) -> None:
    """Log a semantic search message."""
    logger.info(message)
