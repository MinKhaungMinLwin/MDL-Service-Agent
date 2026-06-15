"""Two-level cache for query text embeddings.

The rule and activity semantic passes embed per-request query strings. Across
repeated requests (e.g. re-running the same input CSV during testing) the same
query texts are embedded again, paying Azure round-trips each time.

Two levels:
- In-process hot cache (_hot): survives across API requests within the same server process.
- Disk cache (pickle per model+dimensions): survives across server restarts.

On a warm run (same MDL file, same embedding model), 100% of queries hit the
disk cache and no Azure API calls are made. Total generate time drops from ~400s
to ~80s (the non-embedding overhead).
"""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from common.embedding_client import AzureEmbeddingService

_lock = Lock()
_hot: dict[str, list[float]] = {}      # in-process hot cache
_disk_loaded: set[str] = set()         # "model:dims" slots already loaded from disk

_CACHE_DIR = Path("output/schedule_service/cache")


def _disk_path(model: str, dimensions: int) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", model)
    return _CACHE_DIR / f"qembed_{safe}_{dimensions}.pkl"


def _ensure_loaded(model: str, dimensions: int) -> None:
    """Populate _hot from disk cache if not already done (must be called under _lock)."""
    slot = f"{model}:{dimensions}"
    if slot in _disk_loaded:
        return
    path = _disk_path(model, dimensions)
    if path.exists():
        try:
            data: dict[str, list[float]] = pickle.loads(path.read_bytes())
            _hot.update(data)
            logger.info("Embedding disk cache loaded: {} entries ({})", len(data), path.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding disk cache unreadable ({}), starting fresh", exc)
    _disk_loaded.add(slot)


def _write_disk(snapshot: dict[str, list[float]], model: str, dimensions: int) -> None:
    """Write snapshot to disk atomically. Called outside _lock."""
    path = _disk_path(model, dimensions)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".pkl.tmp")
    try:
        tmp.write_bytes(pickle.dumps(snapshot))
        tmp.replace(path)
        logger.debug("Embedding disk cache saved: {} entries → {}", len(snapshot), path.name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding disk cache write failed ({}), continuing without persistence", exc)


def embed_texts_cached(service: AzureEmbeddingService, texts: list[str]) -> list[list[float]]:
    """Return embeddings for *texts*, embedding only those not already cached.

    Order of the returned list matches *texts*. Thread-safe.
    New embeddings are persisted to disk so subsequent server restarts skip
    Azure API calls for previously seen queries.
    """
    with _lock:
        _ensure_loaded(service.model, service.dimensions)
        missing = [t for t in dict.fromkeys(texts) if t not in _hot]

    if missing:
        logger.info(
            "Embedding cache: {} new of {} unique texts (hit rate {:.0%})",
            len(missing),
            len(dict.fromkeys(texts)),
            1 - len(missing) / max(len(dict.fromkeys(texts)), 1),
        )
        embeddings = service.embed_texts(missing)
        with _lock:
            for text, emb in zip(missing, embeddings, strict=True):
                _hot[text] = emb
            snapshot = dict(_hot)
        _write_disk(snapshot, service.model, service.dimensions)
    else:
        logger.info(
            "Embedding cache: all {} unique texts cached (100%)",
            len(dict.fromkeys(texts)),
        )

    with _lock:
        return [_hot[t] for t in texts]


def clear() -> None:
    """Clear in-process embedding cache (test/maintenance use). Does not delete disk cache."""
    with _lock:
        _hot.clear()
        _disk_loaded.clear()
