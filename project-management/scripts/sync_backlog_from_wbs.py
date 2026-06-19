#!/usr/bin/env python3
"""Sync data/backlog.json from content/ko/wbs.md WBS table."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WBS_KO = ROOT / "content" / "ko" / "wbs.md"
WBS_EN = ROOT / "content" / "en" / "wbs.md"
BACKLOG_KO = ROOT / "data" / "backlog.json"
BACKLOG_EN = ROOT / "data" / "backlog.en.json"

STATUS_MAP = {
    "완료": "완료",
    "진행중": "진행중",
    "진행예정": "진행예정",
    "Done": "완료",
    "In Progress": "진행중",
    "Planned": "진행예정",
}


def strip_wrapper(text: str) -> str:
    return re.sub(r"^<!-- html -->\s*", "", text.strip())


def parse_wbs_items(html: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current_l1 = ""
    current_l2 = ""

    for line in html.splitlines():
        m = re.search(r'class="l1-cell[^"]*"[^>]*>([^<]+)</td>', line)
        if m:
            current_l1 = m.group(1).strip()
            if "l1-merged" in line:
                current_l2 = current_l1
            continue

        m = re.search(r'class="l2-cell"[^>]*>([^<]+)</td>', line)
        if m:
            current_l2 = m.group(1).strip()
            continue

        m = re.search(r'class="task-cell"[^>]*>([^<]+)</td>', line)
        if not m:
            continue
        task = m.group(1).strip()

        status = "진행예정"
        sm = re.search(r'status-badge[^"]*">([^<]+)</span>', line)
        if not sm:
            # status on next line in source
            pass
        else:
            status = STATUS_MAP.get(sm.group(1).strip(), sm.group(1).strip())

        # status may be on same row block - check line after task line pattern
        items.append(
            {
                "l1": current_l1,
                "l2": current_l2 or current_l1,
                "task": task,
                "status": status,
                "deliverable": "",
            }
        )

    # Fix status: often on line after task-cell line
    lines = html.splitlines()
    idx = 0
    fixed: list[dict[str, str]] = []
    current_l1 = ""
    current_l2 = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.search(r'class="l1-cell[^"]*"[^>]*>([^<]+)</td>', line)
        if m:
            current_l1 = m.group(1).strip()
            current_l2 = current_l1 if "l1-merged" in line else current_l2
            i += 1
            continue
        m = re.search(r'class="l2-cell"[^>]*>([^<]+)</td>', line)
        if m:
            current_l2 = m.group(1).strip()
            i += 1
            continue
        m = re.search(r'class="task-cell"[^>]*>([^<]+)</td>', line)
        if m:
            task = m.group(1).strip()
            status = "진행예정"
            for j in range(i, min(i + 3, len(lines))):
                sm = re.search(r'status-badge[^"]*">([^<]+)</span>', lines[j])
                if sm:
                    raw = sm.group(1).strip()
                    status = STATUS_MAP.get(raw, raw)
                    break
            fixed.append(
                {
                    "l1": current_l1,
                    "l2": current_l2 or current_l1,
                    "task": task,
                    "status": status,
                    "deliverable": "",
                }
            )
        i += 1

    return fixed


def to_backlog(items: list[dict[str, str]], id_prefix: str = "bl") -> list[dict]:
    return [
        {
            "id": f"{id_prefix}-{i:03d}",
            **item,
        }
        for i, item in enumerate(items, start=1)
    ]


def main() -> int:
    ko_html = strip_wrapper(WBS_KO.read_text(encoding="utf-8"))
    en_html = strip_wrapper(WBS_EN.read_text(encoding="utf-8"))

    ko_items = parse_wbs_items(ko_html)
    en_items = parse_wbs_items(en_html)

    if len(ko_items) != len(en_items):
        print(f"Warning: ko={len(ko_items)} en={len(en_items)} item count mismatch")

    ko_backlog = to_backlog(ko_items)
    en_backlog = [
        {
            "id": ko_backlog[i]["id"],
            "l1": en_items[i]["l1"],
            "l2": en_items[i]["l2"],
            "task": en_items[i]["task"],
            "deliverable": en_items[i].get("deliverable", ""),
        }
        for i in range(min(len(ko_backlog), len(en_items)))
    ]

    BACKLOG_KO.write_text(json.dumps(ko_backlog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BACKLOG_EN.write_text(json.dumps(en_backlog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(ko_backlog)} items to {BACKLOG_KO.name} and {BACKLOG_EN.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
