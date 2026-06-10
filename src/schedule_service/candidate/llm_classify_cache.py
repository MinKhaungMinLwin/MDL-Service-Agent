"""Disk cache for MDL LLM classification results, keyed by document title.

Classifying a title (Equipment/Building/System/Deliverable) is a per-title LLM
round-trip and is the dominant cost of /schedule/candidates?classify_with_llm=true.
The mapping title → fields is deterministic for a given prompt, so caching it on
disk lets repeated runs (e.g. re-testing the same input CSV) skip the LLM entirely.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

DEFAULT_CACHE_PATH = Path("output/schedule_service/cache/llm_classify_cache.json")
_FIELDS = ("equipment", "building", "system", "deliverable")
_lock = Lock()


def _key(title: str) -> str:
    return hashlib.sha256(title.strip().lower().encode("utf-8")).hexdigest()[:16]


class LLMClassifyCache:
    """JSON-backed title → classification-fields cache."""

    def __init__(self, path: Path = DEFAULT_CACHE_PATH) -> None:
        self.path = path
        self._data: dict[str, dict[str, str]] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — a corrupt cache must never break the request
                self._data = {}

    def get(self, title: str) -> dict[str, str] | None:
        """Return cached fields for *title*, or None on miss."""
        return self._data.get(_key(title))

    def put(self, title: str, fields: dict[str, Any]) -> None:
        """Store the classification fields for *title*."""
        self._data[_key(title)] = {f: str(fields.get(f, "") or "") for f in _FIELDS}

    def save(self) -> None:
        """Persist the cache to disk (atomic write)."""
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
