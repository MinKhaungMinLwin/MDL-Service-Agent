#!/usr/bin/env python3
"""Seed scheduleStart/scheduleEnd in backlog.json from wbs-timeline.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / "data" / "backlog.json"
TIMELINE = ROOT / "data" / "wbs-timeline.json"

WBS_MONTHS = [
    (2026, 4, 5),
    (2026, 5, 4),
    (2026, 6, 4),
    (2026, 7, 5),
    (2026, 8, 4),
    (2026, 9, 5),
    (2026, 10, 4),
]


def days_in_month(year: int, month: int) -> int:
    import calendar
    return calendar.monthrange(year, month)[1]


def build_week_ranges() -> list[tuple[str, str]]:
    ranges: list[tuple[str, str]] = []
    for year, month, weeks in WBS_MONTHS:
        dim = days_in_month(year, month)
        day = 1
        for w in range(weeks):
            remaining_weeks = weeks - w
            remaining_days = dim - day + 1
            span = max(1, remaining_days // remaining_weeks)
            end_day = min(day + span - 1, dim)
            ranges.append(
                (f"{year:04d}-{month:02d}-{day:02d}", f"{year:04d}-{month:02d}-{end_day:02d}")
            )
            day = end_day + 1
    return ranges


def timeline_to_schedule(timeline: list[str], ranges: list[tuple[str, str]]) -> tuple[str, str]:
    indices = [i for i, cell in enumerate(timeline) if cell]
    if not indices:
        return "", ""
    first, last = indices[0], indices[-1]
    return ranges[first][0], ranges[last][1]


def main() -> int:
    ranges = build_week_ranges()
    timeline = json.loads(TIMELINE.read_text(encoding="utf-8"))
    backlog = json.loads(BACKLOG.read_text(encoding="utf-8"))

    for item in backlog:
        tl = timeline.get(item["id"], [])
        start, end = timeline_to_schedule(tl, ranges)
        item["scheduleStart"] = start
        item["scheduleEnd"] = end

    BACKLOG.write_text(json.dumps(backlog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    seeded = sum(1 for i in backlog if i.get("scheduleStart"))
    print(f"Updated {len(backlog)} items, {seeded} with schedule dates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
