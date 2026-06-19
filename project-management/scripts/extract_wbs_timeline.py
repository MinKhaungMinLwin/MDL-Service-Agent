#!/usr/bin/env python3
"""Extract WBS timeline cells from content/ko/wbs.md into data/wbs-timeline.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WBS_KO = ROOT / "content" / "ko" / "wbs.md"
BACKLOG = ROOT / "data" / "backlog.json"
OUT = ROOT / "data" / "wbs-timeline.json"
META_OUT = ROOT / "data" / "wbs-meta.json"


def strip_wrapper(text: str) -> str:
    return re.sub(r"^<!-- html -->\s*", "", text.strip())


def parse_timeline_rows(html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    in_tbody = False
    row_lines: list[str] = []

    for line in html.splitlines():
        if "<tbody>" in line:
            in_tbody = True
            continue
        if "</tbody>" in line:
            break
        if not in_tbody:
            continue
        if "<tr>" in line:
            row_lines = [line]
            if "</tr>" in line:
                rows.append(extract_timeline_from_row("\n".join(row_lines)))
                row_lines = []
            continue
        if row_lines:
            row_lines.append(line)
            if "</tr>" in line:
                rows.append(extract_timeline_from_row("\n".join(row_lines)))
                row_lines = []
    return rows


def extract_timeline_from_row(row_html: str) -> list[str]:
    cells: list[str] = []
    for m in re.finditer(r'class="([^"]*tl-cell[^"]*)"', row_html):
        classes = m.group(1).split()
        tl = next((c for c in classes if c.startswith("tl-") and c != "tl-cell"), "")
        cells.append(tl)
    return cells


def parse_table_headers(html: str) -> dict:
    months: list[dict] = []
    week_labels: list[str] = []
    month_start_indices: list[int] = []

    lines = html.splitlines()
    for i, line in enumerate(lines):
        if 'class="month-header' in line:
            m = re.search(r'colspan="(\d+)"[^>]*>([^<]+)</th>', line)
            if m:
                months.append({"label": m.group(2).strip(), "weeks": int(m.group(1))})
        if "<tbody>" in line:
            break

    for line in lines:
        if 'class="week-col' in line:
            wm = re.search(r'class="([^"]*)"[^>]*>([^<]*)</th>', line)
            if wm:
                week_labels.append(wm.group(2).strip())
                if "month-start" in wm.group(1):
                    month_start_indices.append(len(week_labels) - 1)

    return {
        "weekCount": len(week_labels),
        "months": months,
        "weekLabels": week_labels,
        "monthStartWeekIndices": month_start_indices,
    }


def main() -> int:
    html = strip_wrapper(WBS_KO.read_text(encoding="utf-8"))
    backlog = json.loads(BACKLOG.read_text(encoding="utf-8"))
    timeline_rows = parse_timeline_rows(html)
    meta = parse_table_headers(html)

    if len(timeline_rows) != len(backlog):
        print(
            f"Warning: timeline rows={len(timeline_rows)} backlog={len(backlog)}",
        )

    timeline: dict[str, list[str]] = {}
    for i, item in enumerate(backlog):
        if i < len(timeline_rows):
            timeline[item["id"]] = timeline_rows[i]
        else:
            timeline[item["id"]] = [""] * meta["weekCount"]

    OUT.write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    META_OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(timeline)} timelines to {OUT.name}, meta to {META_OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
