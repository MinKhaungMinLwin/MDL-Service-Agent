"""Semantic embedding index for CCPP guide schedule activity matching."""

from __future__ import annotations

from pathlib import Path

from schedule_service.generate._shared.cosine_index import CosineIndex
from schedule_service.generate.activity.models import ScheduleActivity


class SemanticIndex(CosineIndex):
    """Cosine-similarity index over embedded activity target texts."""

    _CACHE_FILENAME = "activity_semantic_embeddings.json"

    @classmethod
    def build(
        cls,
        activities: list[ScheduleActivity],
        cache_dir: Path,
        force_rebuild: bool = False,
    ) -> SemanticIndex:
        """Build (or load from disk cache) the semantic index for *activities*."""
        texts = [activity.semantic_text for activity in activities]
        return cls._build_from_texts(texts, cache_dir, cls._CACHE_FILENAME, force_rebuild)
