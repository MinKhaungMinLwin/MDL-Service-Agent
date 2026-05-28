"""Shared schedule service models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduleActivity:
    """Clean schedule activity used for retrieval and generation."""

    activity_id: str
    activity_name: str
    activity_name_clean: str
    wbs_path: str
    start_date: str
    finish_date: str
    target_text: str


@dataclass(frozen=True)
class Candidate:
    """Ranked candidate schedule activity."""

    activity: ScheduleActivity
    bm25_rank: int | None
    semantic_rank: int | None
    bm25_score: float
    semantic_score: float
    rrf_score: float
