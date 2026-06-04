"""Data models for CCPP guide schedule activity matching."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduleActivity:
    """Clean schedule activity used for retrieval and FA/FC date anchoring."""

    activity_id: str
    activity_name: str
    activity_name_clean: str
    wbs_path: str
    start_date: str
    finish_date: str
    target_text: str
    # Milestone dates — empty until client provides official mapping
    po_start_date: str = ""
    po_finish_date: str = ""
    ntp_date: str = ""
    icod_date: str = ""
    pcod_date: str = ""


@dataclass(frozen=True)
class Candidate:
    """Ranked candidate schedule activity (BM25 + semantic + RRF)."""

    activity: ScheduleActivity
    bm25_rank: int | None
    semantic_rank: int | None
    bm25_score: float
    semantic_score: float
    rrf_score: float
