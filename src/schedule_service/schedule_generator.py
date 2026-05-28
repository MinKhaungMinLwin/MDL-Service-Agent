"""Generate baseline schedule outputs from schedule mapping results."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from loguru import logger

from schedule_service.models import ScheduleActivity
from schedule_service.output_writer import write_schedule_outputs
from schedule_service.schedule_loader import DEFAULT_SCHEDULE_PATH, load_schedule_activities

DEFAULT_OUTPUT_DIR = Path("output/schedule_service")


def generate_schedule_file(
    mapping_json: Path,
    schedule_activities: list[ScheduleActivity],
    output_dir: Path,
    limit: int = 0,
) -> tuple[Path, Path]:
    _log(f"Reading schedule mapping: {mapping_json}")
    mapping_rows = _read_mapping_rows(mapping_json)
    original_row_count = len(mapping_rows)
    if limit > 0:
        mapping_rows = mapping_rows[:limit]
        _log(f"Limit enabled: processing first {len(mapping_rows)} of {original_row_count} rows")
    if not mapping_rows:
        raise ValueError(f"No mapping rows found in {mapping_json}")

    activity_by_id = {activity.activity_id: activity for activity in schedule_activities}
    output_rows = [_format_schedule_row(mapping_json, row, activity_by_id) for row in mapping_rows]

    output_stem = _output_stem(mapping_json)
    if limit > 0:
        output_stem = f"{output_stem}_limit{limit}"
    _log(f"Writing generated schedule with stem: {output_stem}")
    return write_schedule_outputs(output_dir, output_stem, output_rows)


def _format_schedule_row(
    mapping_json: Path,
    row: dict[str, Any],
    activity_by_id: dict[str, ScheduleActivity],
) -> dict[str, Any]:
    selected_activity_id = str(row.get("llm_selected_activity_id", "")).strip()
    activity = activity_by_id.get(selected_activity_id)
    rank = _to_int(row.get("llm_selected_rank", ""))
    selected_candidate = _candidate_fields(row, rank)

    if activity:
        activity_name = activity.activity_name_clean or activity.activity_name
        wbs_path = activity.wbs_path
        start_date = activity.start_date
        finish_date = activity.finish_date
        status = "generated"
    else:
        activity_name = str(selected_candidate.get("activity_name", ""))
        wbs_path = str(selected_candidate.get("wbs_path", ""))
        start_date = str(selected_candidate.get("start_date", ""))
        finish_date = str(selected_candidate.get("finish_date", ""))
        status = "missing_activity" if selected_activity_id else "unmapped"

    return {
        "source_mapping_file": mapping_json.name,
        "source_match_file": row.get("source_file", ""),
        "document": row.get("document", ""),
        "page": row.get("page", ""),
        "search_query": row.get("search_query", ""),
        "search_query_source": row.get("search_query_source", ""),
        "keywords": row.get("keywords", ""),
        "depth_context": row.get("depth_context", ""),
        "selected_activity_id": selected_activity_id,
        "selected_activity_name": activity_name,
        "selected_activity_wbs_path": wbs_path,
        "selected_activity_start_date": start_date,
        "selected_activity_finish_date": finish_date,
        "baseline_schedule_source": "ccpp_guide_activity",
        "schedule_generation_status": status,
        "llm_selected_rank": row.get("llm_selected_rank", ""),
        "llm_confidence": row.get("llm_confidence", ""),
        "llm_status": row.get("llm_status", ""),
        "llm_reason": row.get("llm_reason", ""),
    }


def _candidate_fields(row: dict[str, Any], rank: int | None) -> dict[str, Any]:
    if rank is None or rank < 1:
        return {}
    prefix = f"candidate_{rank}"
    return {
        "activity_name": row.get(f"{prefix}_activity_name", ""),
        "wbs_path": row.get(f"{prefix}_wbs_path", ""),
        "start_date": row.get(f"{prefix}_start_date", ""),
        "finish_date": row.get(f"{prefix}_finish_date", ""),
    }


def _read_mapping_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list in {path}")
    return [row for row in payload if isinstance(row, dict)]


def _output_stem(mapping_json: Path) -> str:
    stem = mapping_json.stem
    if stem.startswith("schedule_mapping_"):
        return f"generated_schedule_{stem.removeprefix('schedule_mapping_')}"
    return f"generated_schedule_{stem}"


def _to_int(value: Any) -> int | None:
    text = str(value).strip()
    if not re.fullmatch(r"\d+", text):
        return None
    return int(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate baseline schedule outputs from schedule mapping JSON files.")
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N rows from each mapping file.")
    parser.add_argument("inputs", nargs="+", type=Path, help="One or more schedule_mapping_*.json files.")
    args = parser.parse_args()

    _log(f"Loading schedule activities: {args.schedule}")
    activities = load_schedule_activities(args.schedule)
    _log(f"Loaded {len(activities)} schedule activities")
    for mapping_json in args.inputs:
        xlsx_path, json_path = generate_schedule_file(
            mapping_json=mapping_json,
            schedule_activities=activities,
            output_dir=args.output_dir,
            limit=args.limit,
        )
        logger.info("Wrote generated schedule workbook: {}", xlsx_path)
        logger.info("Wrote generated schedule JSON: {}", json_path)


def _log(message: str) -> None:
    logger.info(message)


if __name__ == "__main__":
    main()
