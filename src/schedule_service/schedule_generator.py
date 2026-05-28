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

from datetime import date

from loguru import logger

from schedule_service.date_range_engine import DateRange, compute_date_range
from schedule_service.models import ScheduleActivity
from schedule_service.output_writer import write_schedule_outputs
from schedule_service.rule_loader import DEFAULT_RULE_PATH, RuleTable, ValidationRule
from schedule_service.schedule_loader import DEFAULT_SCHEDULE_PATH, load_schedule_activities

DEFAULT_OUTPUT_DIR = Path("output/schedule_service")

# Activity keywords that indicate finish_date should be used as anchor
_FINISH_DATE_KEYWORDS = {"transportation", "delivery", "fob", "manufacturing", "fo b"}


def generate_schedule_file(
    mapping_json: Path,
    schedule_activities: list[ScheduleActivity],
    output_dir: Path,
    rule_path: Path = DEFAULT_RULE_PATH,
    limit: int = 0,
) -> tuple[Path, Path]:
    """Generate baseline schedule outputs from a mapping JSON."""
    _log(f"Reading schedule mapping: {mapping_json}")
    mapping_rows = _read_mapping_rows(mapping_json)
    original_row_count = len(mapping_rows)
    if limit > 0:
        mapping_rows = mapping_rows[:limit]
        _log(f"Limit enabled: processing first {len(mapping_rows)} of {original_row_count} rows")
    if not mapping_rows:
        raise ValueError(f"No mapping rows found in {mapping_json}")

    rule_table = _load_rule_table(rule_path)
    activity_by_id = {activity.activity_id: activity for activity in schedule_activities}
    output_rows = [_format_schedule_row(mapping_json, row, activity_by_id, rule_table) for row in mapping_rows]

    output_stem = _output_stem(mapping_json)
    if limit > 0:
        output_stem = f"{output_stem}_limit{limit}"
    _log(f"Writing generated schedule with stem: {output_stem}")
    return write_schedule_outputs(output_dir, output_stem, output_rows)


def _format_schedule_row(
    mapping_json: Path,
    row: dict[str, Any],
    activity_by_id: dict[str, ScheduleActivity],
    rule_table: RuleTable | None,
) -> dict[str, Any]:
    """Format one generated schedule row, including FA/FC date ranges."""
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

    # Compute FA/FC date ranges via validation rule
    sub_type = ""
    date_range_status = "no_rule"
    dr = DateRange()
    if rule_table is not None:
        document = row.get("document", "")
        rule = rule_table.match(document)
        if rule:
            sub_type = rule.sub_type
            if rule.sub_type == "SKIP":
                date_range_status = "skip"
            else:
                anchor = _resolve_anchor_date(activity, start_date, finish_date, rule)
                dr = compute_date_range(rule.vt_parsed, anchor, rule.sub_type, rule.priority)
                date_range_status = "generated" if anchor is not None else "missing_date"

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
        # Validation rule & submission type
        "submission_type": sub_type,
        # FA date range
        "fa_earliest": _fmt_date(dr.fa_earliest),
        "fa_latest": _fmt_date(dr.fa_latest),
        "fa_recommended": _fmt_date(dr.fa_recommended),
        # FC date range
        "fc_earliest": _fmt_date(dr.fc_earliest),
        "fc_latest": _fmt_date(dr.fc_latest),
        "fc_recommended": _fmt_date(dr.fc_recommended),
        "date_range_status": date_range_status,
        "date_range_confidence": f"{dr.confidence:.2f}" if dr.confidence else "",
        # LLM metadata
        "llm_selected_rank": row.get("llm_selected_rank", ""),
        "llm_confidence": row.get("llm_confidence", ""),
        "llm_status": row.get("llm_status", ""),
        "llm_reason": row.get("llm_reason", ""),
    }


def _load_rule_table(path: Path) -> RuleTable | None:
    """Load rule table; return None if file is missing (graceful degradation)."""
    if not path.exists():
        _log(f"Validation rule file not found: {path} — date ranges will be skipped")
        return None
    table = RuleTable.load(path)
    _log(f"Loaded {len(table._rules)} validation rules from {path}")
    return table


def _resolve_anchor_date(
    activity: ScheduleActivity | None,
    start_date_str: str,
    finish_date_str: str,
    rule: ValidationRule,
) -> date | None:
    """Pick start_date or finish_date as anchor based on rule activity keywords."""
    kws_lower = {k.lower() for k in rule.activity_keywords}
    use_finish = bool(kws_lower & _FINISH_DATE_KEYWORDS)
    date_str = finish_date_str if use_finish else start_date_str
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def _fmt_date(d: date | None) -> str:
    return d.isoformat() if d is not None else ""


def _candidate_fields(row: dict[str, Any], rank: int | None) -> dict[str, Any]:
    """Return selected candidate fields from a mapping row."""
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
    """Read mapping rows from a JSON list."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list in {path}")
    return [row for row in payload if isinstance(row, dict)]


def _output_stem(mapping_json: Path) -> str:
    """Build the generated schedule output stem."""
    stem = mapping_json.stem
    if stem.startswith("schedule_mapping_"):
        return f"generated_schedule_{stem.removeprefix('schedule_mapping_')}"
    return f"generated_schedule_{stem}"


def _to_int(value: Any) -> int | None:
    """Parse a positive integer string."""
    text = str(value).strip()
    if not re.fullmatch(r"\d+", text):
        return None
    return int(text)


def main() -> None:
    """Run the schedule generator CLI."""
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
    """Log a schedule generator message."""
    logger.info(message)


if __name__ == "__main__":
    main()
