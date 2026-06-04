"""Process-level cache for query text embeddings.

The rule and activity semantic passes embed per-request query strings. Across
repeated requests (e.g. re-running the same input CSV during testing) the same
query texts are embedded again, paying Azure round-trips each time. This caches
text → embedding in-process so only previously unseen texts hit the API.
"""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from common.embedding_client import AzureEmbeddingService

_lock = Lock()
_cache: dict[str, list[float]] = {}


def embed_texts_cached(service: AzureEmbeddingService, texts: list[str]) -> list[list[float]]:
    """Return embeddings for *texts*, embedding only those not already cached.

    Order of the returned list matches *texts*. Thread-safe.
    """
    with _lock:
        missing = [t for t in dict.fromkeys(texts) if t not in _cache]

    if missing:
        logger.info("Embedding cache: {} new of {} unique texts (hit rate {:.0%})",
                    len(missing), len(dict.fromkeys(texts)),
                    1 - len(missing) / max(len(dict.fromkeys(texts)), 1))
        embeddings = service.embed_texts(missing)
        with _lock:
            for text, emb in zip(missing, embeddings, strict=True):
                _cache[text] = emb

    with _lock:
        return [_cache[t] for t in texts]


def clear() -> None:
    """Clear the embedding cache (test/maintenance use)."""
    with _lock:
        _cache.clear()
