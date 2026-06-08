"""Shared cosine-similarity embedding index (numpy-backed), disk-cached by corpus hash.

Base class for the two semantic indexes used in /schedule/generate:
- activity.semantic.SemanticIndex   (corpus = activity semantic_text)
- rule.semantic.RuleSemanticIndex   (corpus = rule doc_keyword + item_name)

Both embed a fixed corpus once at build time, cache it on disk keyed by a SHA-256 of
all corpus texts (auto-invalidates when the data changes), and expose the same scoring
surface. Subclasses only supply the corpus texts and a cache filename.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from loguru import logger

from common.embedding_client import AzureEmbeddingService


class CosineIndex:
    """In-memory cosine-similarity index over a fixed corpus of normalized embeddings."""

    def __init__(self, embeddings: list[list[float]]) -> None:
        """Normalize and store the corpus embeddings as a float32 matrix."""
        normalized = [_normalize_vector(e) for e in embeddings]
        self.matrix = np.array(normalized, dtype=np.float32)  # (n_docs, dims)
        self._embedding_service: AzureEmbeddingService | None = None

    # ------------------------------------------------------------------ build

    @classmethod
    def _build_from_texts(
        cls,
        texts: list[str],
        cache_dir: Path,
        cache_filename: str,
        force_rebuild: bool = False,
    ) -> CosineIndex:
        """Embed *texts* once (or load from the on-disk cache) and return an index."""
        key = _hash_texts(texts)
        cache_path = cache_dir / cache_filename

        if not force_rebuild and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("key") == key:
                    logger.info("{} cache HIT ({} docs)", cls.__name__, len(texts))
                    return cls(cached["embeddings"])
                logger.info("{} cache STALE — rebuilding", cls.__name__)
            except Exception as exc:  # noqa: BLE001 — a corrupt cache must never break a request
                logger.warning("{} cache unreadable ({}), rebuilding", cls.__name__, exc)

        logger.info("Embedding {} texts for {}", len(texts), cls.__name__)
        service = AzureEmbeddingService()
        embeddings = service.embed_texts(texts)

        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"key": key, "embeddings": embeddings}, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("{} built and cached → {}", cls.__name__, cache_path)
        return cls(embeddings)

    # ------------------------------------------------------------------ score

    def score_matrix(self, query_embeddings: np.ndarray) -> np.ndarray:
        """Cosine similarity for many queries at once.

        Args:
            query_embeddings: raw (unnormalized) embeddings, shape (n_queries, dims).
        Returns:
            cosine similarities, shape (n_queries, n_docs).
        """
        q = np.asarray(query_embeddings, dtype=np.float32)
        norms = np.linalg.norm(q, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return (q / norms) @ self.matrix.T

    def score_embedding(self, query_embedding: list[float]) -> list[float]:
        """Cosine similarity between one pre-computed query embedding and all docs."""
        q = np.array(_normalize_vector(query_embedding), dtype=np.float32)
        return (self.matrix @ q).tolist()

    def score(self, query: str) -> list[float]:
        """Embed *query* (Azure round-trip) then score against all docs."""
        if self._embedding_service is None:
            self._embedding_service = AzureEmbeddingService()
        return self.score_embedding(self._embedding_service.embed_text(query))


def _normalize_vector(vector: list[float]) -> list[float]:
    """Normalize a vector for cosine similarity."""
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _hash_texts(texts: list[str]) -> str:
    combined = "\n".join(texts).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()[:16]
