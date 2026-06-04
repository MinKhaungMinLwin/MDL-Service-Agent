"""Load cleaned CCPP guide schedule data."""

from __future__ import annotations

import json
from pathlib import Path

from common.text_normalizer import build_schedule_target_text
from schedule_service.models import ScheduleActivity

DEFAULT_SCHEDULE_PATH = Path("data/schedule_service/processed/ccpp_guide_schedule_260527_clean.json")


def load_schedule_activities(schedule_path: Path) -> list[ScheduleActivity]:
    """Load activity rows from a cleaned guide schedule JSON file."""
    payload = json.loads(schedule_path.read_text(encoding="utf-8"))
    activities: list[ScheduleActivity] = []
    for row in payload["rows"]:
        if row.get("row_type") != "activity":
            continue

        activity_name_clean = row.get("activity_name_clean", "").strip()
        wbs_path = row.get("wbs_path", "").strip()
        activity_id = row.get("activity_id", "").strip()
        target_text = build_schedule_target_text(
            activity_name=activity_name_clean,
            wbs_path=wbs_path,
            activity_id=activity_id,
        )
        activities.append(
            ScheduleActivity(
                activity_id=activity_id,
                activity_name=row.get("activity_name", "").strip(),
                activity_name_clean=activity_name_clean,
                wbs_path=wbs_path,
                start_date=row.get("start_date", "").strip(),
                finish_date=row.get("finish_date", "").strip(),
                target_text=target_text,
            )
        )
    return activities
