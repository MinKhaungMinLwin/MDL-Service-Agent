"""Generate FA/FC date ranges from MDL classified documents.

Thin orchestration only: read the CSV, resolve a validation rule and a CCPP activity for
every row (delegated to rule.matcher / activity.matcher), compute date ranges, and write
the output. All matching logic lives in the rule/ and activity/ subpackages.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from loguru import logger

from schedule_service.generate._shared.resource_cache import (
    get_activity_semantic_index,
    get_bm25_index,
    get_rule_matcher,
    get_rule_semantic_index,
)
from schedule_service.generate.activity.loader import DEFAULT_SCHEDULE_PATH, load_schedule_activities
from schedule_service.generate.activity.matcher import resolve_activities, resolve_anchor_date
from schedule_service.generate.activity.models import ScheduleActivity
from schedule_service.generate.date.date_range_engine import DateRange, compute_date_range
from schedule_service.generate.rule.loader import DEFAULT_RULE_PATH
from schedule_service.generate.rule.matcher import build_rule_query, resolve_rules
from schedule_service.generate.rule.models import ValidationRule
from schedule_service.output_writer import write_schedule_outputs

DEFAULT_OUTPUT_DIR = Path("output/schedule_service/generate")

# All dates in the CCPP guide schedule are relative to this template NTP.
TEMPLATE_NTP = date(2007, 3, 1)


@dataclass(frozen=True)
class MatchContext:
    """The validation rule and CCPP guide schedule activity resolved for one MDL row."""

    rule: ValidationRule | None
    activity: ScheduleActivity


def generate_schedule_file(
    input_csv: Path,
    schedule_activities: list[ScheduleActivity],
    output_dir: Path,
    rule_path: Path = DEFAULT_RULE_PATH,
    limit: int = 0,
    ntp_date: str = "",
    semantic_cache_dir: Path | None = None,
    semantic_weight: float = 0.3,
    activity_cache_dir: Path | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Generate FA/FC date ranges from an MDL classified CSV.

    Returns (xlsx_path, json_path, timing) where timing breaks down each processing phase.
    Always uses hybrid (token + semantic) scoring for rule matching and BM25 + semantic + RRF for activity matching.

    Args:
        ntp_date:             Real project NTP date in ISO format (e.g. "2024-01-15").
                              Shifts all guide schedule template dates accordingly.
        semantic_cache_dir:   Path to semantic cache directory for rule embeddings.
        semantic_weight:      Weight of semantic score in hybrid rule scoring (0–1, default 0.3).
        activity_cache_dir:   Path to semantic cache directory for activity embeddings.
    """
    import time

    t0 = time.perf_counter()

    _log(f"Reading MDL classified CSV: {input_csv}")
    rows = _read_csv(input_csv)
    original_count = len(rows)
    if limit > 0:
        rows = rows[:limit]
        _log(f"Limit enabled: processing first {len(rows)} of {original_count} rows")
    if not rows:
        raise ValueError(f"No rows found in {input_csv}")

    t_read = time.perf_counter()

    shift_days = _compute_shift(ntp_date)
    if shift_days:
        _log(f"NTP shift: {ntp_date} → {shift_days:+d} days from template NTP {TEMPLATE_NTP}")
    else:
        _log("No NTP date provided — using guide schedule template dates")

    rule_matcher = get_rule_matcher(rule_path)
    bm25 = get_bm25_index(schedule_activities)

    t_load = time.perf_counter()

    # 1. Resolve the validation rule for every row (always hybrid token + semantic).
    rule_semantic_index = get_rule_semantic_index(rule_matcher, semantic_cache_dir) if rule_matcher else None
    rules = resolve_rules(rows, rule_matcher, rule_semantic_index, semantic_weight)

    t_rules = time.perf_counter()

    # 2. Resolve the CCPP activity for every row (always BM25 + semantic + RRF), rule-boosted.
    activity_semantic_index = get_activity_semantic_index(
        schedule_activities, activity_cache_dir or output_dir / "activity_semantic_cache"
    )
    activities = resolve_activities(rows, schedule_activities, bm25, rules, activity_semantic_index)

    t_activities = time.perf_counter()

    # 3. Render output rows from the resolved matches.
    contexts = [MatchContext(rule=r, activity=a) for r, a in zip(rules, activities, strict=True)]
    output_rows = [
        _format_schedule_row(row, ctx, shift_days)
        for row, ctx in zip(rows, contexts, strict=True)
    ]

    t_format = time.perf_counter()

    output_stem = _output_stem(input_csv)
    if ntp_date:
        output_stem = f"{output_stem}_ntp{ntp_date}"
    if limit > 0:
        output_stem = f"{output_stem}_limit{limit}"
    _log(f"Writing generated schedule with stem: {output_stem}")
    xlsx_path, json_path = write_schedule_outputs(output_dir, output_stem, output_rows)

    t_end = time.perf_counter()

    timing: dict[str, Any] = {
        "csv_read_s": round(t_read - t0, 3),
        "loader_setup_s": round(t_load - t_read, 3),
        "rule_resolution_s": round(t_rules - t_load, 3),
        "activity_resolution_s": round(t_activities - t_rules, 3),
        "format_s": round(t_format - t_activities, 3),
        "write_s": round(t_end - t_format, 3),
        "total_s": round(t_end - t0, 3),
        "rows_processed": len(rows),
        "use_semantic_rules": bool(rule_semantic_index),
        "use_semantic_activities": bool(activity_semantic_index),
    }
    logger.info(
        "Timing — read: {csv_read_s}s | loader: {loader_setup_s}s"
        " | rules: {rule_resolution_s}s | activities: {activity_resolution_s}s"
        " | format: {format_s}s | write: {write_s}s | total: {total_s}s",
        **timing,
    )
    return xlsx_path, json_path, timing


def _format_schedule_row(
    row: dict[str, str],
    ctx: MatchContext,
    shift_days: int = 0,
) -> dict[str, Any]:
    """Format one generated schedule row with FA/FC date ranges from a resolved match."""
    title = row.get("Title", "").strip()
    deliverable = row.get("Deliverable", "").strip()
    equipment = row.get("Equipment", "").strip()
    system = row.get("System", "").strip()
    building = row.get("Building", "").strip()

    rule_query = build_rule_query(row)
    rule = ctx.rule
    activity = ctx.activity

    sub_type = rule.sub_type if rule else ""
    rule_name = rule.item_name if rule else ""
    vt_parsed: dict = rule.vt_parsed if rule else {}

    # Compute FA/FC date ranges
    dr = DateRange()
    date_range_status = "no_rule"
    if rule and sub_type == "SKIP":
        date_range_status = "skip"
    elif rule:
        anchor = resolve_anchor_date(activity.start_date, activity.finish_date, rule, shift_days)
        ntp_floor = TEMPLATE_NTP + timedelta(days=shift_days) if shift_days else None
        dr = compute_date_range(vt_parsed, anchor, sub_type, rule.priority, ntp_floor=ntp_floor)
        date_range_status = "generated" if anchor is not None else "missing_date"

    return {
        "source_file": row.get("Source File", ""),
        "document_no": row.get("Document No", "").strip(),
        "title": title,
        "deliverable": deliverable,
        "equipment": equipment,
        "system": system,
        "building": building,
        "itb_sources": row.get("itb_sources", ""),
        "rule_query": rule_query,
        "matched_rule": rule_name,
        "submission_type": sub_type,
        "matched_activity_id": activity.activity_id,
        "matched_activity_name": activity.activity_name_clean or activity.activity_name,
        "matched_activity_wbs_path": activity.wbs_path,
        "matched_activity_start_date": activity.start_date,
        "matched_activity_finish_date": activity.finish_date,
        "fa_earliest": _fmt_date(dr.fa_earliest),
        "fa_recommended": _fmt_date(dr.fa_recommended),
        "fa_latest": _fmt_date(dr.fa_latest),
        "fc_earliest": _fmt_date(dr.fc_earliest),
        "fc_recommended": _fmt_date(dr.fc_recommended),
        "fc_latest": _fmt_date(dr.fc_latest),
        "date_range_status": date_range_status,
        "date_range_confidence": f"{dr.confidence:.2f}" if dr.confidence else "",
        "ntp_shift_days": shift_days if shift_days else "",
    }


def _compute_shift(ntp_date: str) -> int:
    """Return days to shift guide schedule dates given a real project NTP date."""
    if not ntp_date:
        return 0
    try:
        return (date.fromisoformat(ntp_date) - TEMPLATE_NTP).days
    except ValueError:
        logger.warning("Invalid ntp_date '{}' — using template dates", ntp_date)
        return 0


def _fmt_date(d: date | None) -> str:
    return d.isoformat() if d is not None else ""


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read an MDL classified CSV file."""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _output_stem(input_csv: Path) -> str:
    """Build the generated schedule output stem."""
    return f"generated_schedule_{input_csv.stem}"


def main() -> None:
    """Run the schedule generator CLI."""
    parser = argparse.ArgumentParser(description="Generate FA/FC date ranges from MDL classified CSV files.")
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N rows from each input CSV.")
    parser.add_argument(
        "--ntp-date",
        default="",
        help="Real project NTP date in ISO format (e.g. 2024-01-15). Shifts all guide schedule dates accordingly.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="One or more *_MDL_classified.csv files.")
    args = parser.parse_args()

    _log(f"Loading schedule activities: {args.schedule}")
    activities = load_schedule_activities(args.schedule)
    _log(f"Loaded {len(activities)} schedule activities")
    for input_csv in args.inputs:
        xlsx_path, json_path, _timing = generate_schedule_file(
            input_csv=input_csv,
            schedule_activities=activities,
            output_dir=args.output_dir,
            limit=args.limit,
            ntp_date=args.ntp_date,
            semantic_cache_dir=args.output_dir / "rule_semantic_cache",
            activity_cache_dir=args.output_dir / "activity_semantic_cache",
        )
        logger.info("Wrote generated schedule workbook: {}", xlsx_path)
        logger.info("Wrote generated schedule JSON: {}", json_path)


def _log(message: str) -> None:
    """Log a schedule generator message."""
    logger.info(message)


if __name__ == "__main__":
    main()
