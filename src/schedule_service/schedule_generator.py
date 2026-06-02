"""Generate FA/FC date ranges from MDL classified documents."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from datetime import date, timedelta

from loguru import logger

from schedule_service.date_range_engine import DateRange, compute_date_range
from schedule_service.models import ScheduleActivity
from schedule_service.output_writer import write_schedule_outputs
from schedule_service.rule_loader import DEFAULT_RULE_PATH, RuleTable, ValidationRule
from schedule_service.schedule_loader import DEFAULT_SCHEDULE_PATH, load_schedule_activities
from schedule_service.search.keyword_search import BM25Index

DEFAULT_OUTPUT_DIR = Path("output/schedule_service")

# All dates in the CCPP guide schedule are relative to this template NTP
TEMPLATE_NTP = date(2007, 3, 1)

# Activity keywords that indicate finish_date should be used as anchor
_FINISH_DATE_KEYWORDS = {"transportation", "delivery", "fob", "manufacturing", "fo b"}

# Maps rule activity_keywords → BM25 phase-boost terms to steer activity selection
# to the correct project phase (early design, delivery, commissioning, etc.)
_ACTIVITY_KW_BOOST: dict[str, str] = {
    "p.o":           "P.O Procurement",
    "po":            "P.O Procurement",
    "pof":           "P.O Procurement finish",
    "delivery":      "transportation delivery",
    "fob":           "transportation delivery FOB",
    "transportation":"transportation delivery",
    "manufacturing": "manufacturing P.O",
    "fo b":          "transportation delivery",
    "commissioning": "commissioning test",
}

# Maps canonical equipment names (from MDL classified CSV) to abbreviations
# used in validation_rule.csv MDL Document Keywords (e.g. "HRSG - P&ID").
# Without this, "Heat Recovery Steam Generator" never intersects with "HRSG" tokens.
_EQUIPMENT_TO_ABBR: dict[str, str] = {
    "Heat Recovery Steam Generator": "HRSG",
    "Gas Turbine Generator": "GTG",
    "Steam Turbine & Generator": "STG",
    "Steam Turbine": "STG",
    "Air Cooled Condenser": "ACC",
    "Condensate Extraction Pump": "CEP",
    "Boiler Feed Pump": "BFP",
    "Fuel Gas Package": "FGP",
    "Balance of Plant": "BOP",
    "Cooling Water Package": "CCWP",
    "Blackstart Emergency Diesel Generator": "BSEDG",
}

# Map MDL Deliverable values to terms used in validation_rule.csv keywords
_DELIVERABLE_NORM: dict[str, str] = {
    "P&I DIAGRAM": "P&ID",
    "P&I DRAWING": "P&ID",
    "P&ID": "P&ID",
    "PIPING & INSTRUMENTATION DRAWING": "P&ID",
    "PIPING AND INSTRUMENTATION DRAWING": "P&ID",
    "PIPING AND INSTRUMENTATION DIAGRAM": "P&ID",
    "GENERAL ARRANGEMENT": "General Arrangement Drawing",
    "GA": "General Arrangement Drawing",
    "GA DRAWING": "General Arrangement Drawing",
    "ARRANGEMENT DRAWING": "General Arrangement Drawing",
    "LAYOUT": "Layout Drawing",
    "LAYOUT DRAWING": "Layout Drawing",
    "CALCULATION": "Calculation sheet",
    "SIZING CALCULATION": "Calculation sheet",
    "TECHNICAL SPECIFICATION": "Technical Specification",
    "SPECIFICATION": "Technical Specification",
    "DATA SHEET": "Data Sheet",
    "DATASHEET": "Data Sheet",
    "OUTLINE DRAWING": "Outline Drawing",
    "SINGLE LINE DIAGRAM": "Single Line Diagram",
    "SLD": "Single Line Diagram",
    "DETAIL": "Detail Drawing",
    "DETAIL DRAWING": "Detail Drawing",
    "ELEVATION": "Elevation Drawing",
    "DIAGRAM": "Diagram",
    "ISOMETRIC": "Isometric Drawing",
    "ISOMETRIC DRAWING": "Isometric Drawing",
    "FOUNDATION AND LOADING DATA": "Foundation and Loading Data",
    "SYSTEM DESCRIPTION": "System Description",
    "PLAN": "Plan",
    "SCHEDULE": "Schedule",
}


def generate_schedule_file(
    input_csv: Path,
    schedule_activities: list[ScheduleActivity],
    output_dir: Path,
    rule_path: Path = DEFAULT_RULE_PATH,
    limit: int = 0,
    ntp_date: str = "",
) -> tuple[Path, Path]:
    """Generate FA/FC date ranges from an MDL classified CSV.

    Args:
        ntp_date: Real project NTP date in ISO format (e.g. "2024-01-15").
                  All guide schedule template dates are shifted by
                  (ntp_date - 2007-03-01) to produce real-world dates.
                  If omitted, template dates (2007–2009) are used as-is.
    """
    _log(f"Reading MDL classified CSV: {input_csv}")
    rows = _read_csv(input_csv)
    original_count = len(rows)
    if limit > 0:
        rows = rows[:limit]
        _log(f"Limit enabled: processing first {len(rows)} of {original_count} rows")
    if not rows:
        raise ValueError(f"No rows found in {input_csv}")

    shift_days = _compute_shift(ntp_date)
    if shift_days:
        _log(f"NTP shift: {ntp_date} → {shift_days:+d} days from template NTP {TEMPLATE_NTP}")
    else:
        _log("No NTP date provided — using guide schedule template dates")

    rule_table = _load_rule_table(rule_path)

    _log(f"Building BM25 index for {len(schedule_activities)} schedule activities")
    bm25 = BM25Index([a.target_text for a in schedule_activities])

    output_rows = [
        _format_schedule_row(row, schedule_activities, bm25, rule_table, shift_days)
        for row in rows
    ]

    output_stem = _output_stem(input_csv)
    if ntp_date:
        output_stem = f"{output_stem}_ntp{ntp_date}"
    if limit > 0:
        output_stem = f"{output_stem}_limit{limit}"
    _log(f"Writing generated schedule with stem: {output_stem}")
    return write_schedule_outputs(output_dir, output_stem, output_rows)


def _format_schedule_row(
    row: dict[str, str],
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    rule_table: RuleTable | None,
    shift_days: int = 0,
) -> dict[str, Any]:
    """Format one generated schedule row with FA/FC date ranges."""
    title = row.get("Title", "").strip()
    deliverable = row.get("Deliverable", "").strip()
    equipment = row.get("Equipment", "").strip()
    system = row.get("System", "").strip()
    building = row.get("Building", "").strip()

    # Build rule match string: normalize(Deliverable) + "for" + abbreviated scope.
    # Rules in validation_rule.csv use abbreviations (HRSG, GTG, STG, ACC…) not
    # canonical full names, so we map before querying to get token overlap.
    norm_del = _normalize_deliverable(deliverable)
    scope = equipment or system or building
    abbr_scope = _EQUIPMENT_TO_ABBR.get(scope, scope)
    rule_query = f"{norm_del} for {abbr_scope}" if abbr_scope else norm_del

    # Match validation rule: try scoped query first, fall back to bare title
    rule: ValidationRule | None = None
    if rule_table:
        rule = rule_table.match(rule_query) or rule_table.match(title)

    sub_type = rule.sub_type if rule else ""
    rule_name = rule.item_name if rule else ""
    vt_parsed: dict = rule.vt_parsed if rule else {}

    # Match CCPP guide schedule activity via BM25
    # Append phase-boost terms from the matched rule's activity_keywords so BM25
    # steers toward the correct project phase (e.g. P.O → procurement activities,
    # delivery → transportation activities, commissioning → test activities).
    activity_query = " ".join(p for p in [equipment, system, norm_del, title] if p)
    if rule:
        boost = _phase_boost(rule.activity_keywords)
        if boost:
            activity_query = f"{activity_query} {boost}"
    bm25_scores = bm25.score(activity_query)
    top_idx = max(range(len(bm25_scores)), key=lambda idx: bm25_scores[idx])
    activity = activities[top_idx]

    # Compute FA/FC date ranges
    dr = DateRange()
    date_range_status = "no_rule"
    if rule and sub_type == "SKIP":
        date_range_status = "skip"
    elif rule:
        anchor = _resolve_anchor_date(activity.start_date, activity.finish_date, rule, shift_days)
        dr = compute_date_range(vt_parsed, anchor, sub_type, rule.priority)
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


def _load_rule_table(path: Path) -> RuleTable | None:
    """Load rule table; return None if file is missing (graceful degradation)."""
    if not path.exists():
        _log(f"Validation rule file not found: {path} — date ranges will be skipped")
        return None
    table = RuleTable.load(path)
    _log(f"Loaded {len(table._rules)} validation rules from {path}")
    return table


def _resolve_anchor_date(
    start_date_str: str,
    finish_date_str: str,
    rule: ValidationRule,
    shift_days: int = 0,
) -> date | None:
    """Pick start_date or finish_date as anchor, then apply NTP shift."""
    kws_lower = {k.lower() for k in rule.activity_keywords}
    use_finish = bool(kws_lower & _FINISH_DATE_KEYWORDS)
    date_str = finish_date_str if use_finish else start_date_str
    if not date_str:
        return None
    try:
        template_date = date.fromisoformat(date_str)
        return template_date + timedelta(days=shift_days)
    except ValueError:
        return None


def _compute_shift(ntp_date: str) -> int:
    """Return days to shift guide schedule dates given a real project NTP date."""
    if not ntp_date:
        return 0
    try:
        return (date.fromisoformat(ntp_date) - TEMPLATE_NTP).days
    except ValueError:
        logger.warning("Invalid ntp_date '{}' — using template dates", ntp_date)
        return 0


def _phase_boost(activity_keywords: list[str]) -> str:
    """Return BM25 boost terms derived from rule activity_keywords."""
    terms = [_ACTIVITY_KW_BOOST[kw.lower().strip()] for kw in activity_keywords
             if kw.lower().strip() in _ACTIVITY_KW_BOOST]
    return " ".join(terms)


def _normalize_deliverable(deliverable: str) -> str:
    return _DELIVERABLE_NORM.get(deliverable.strip().upper(), deliverable.strip())


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
        xlsx_path, json_path = generate_schedule_file(
            input_csv=input_csv,
            schedule_activities=activities,
            output_dir=args.output_dir,
            limit=args.limit,
            ntp_date=args.ntp_date,
        )
        logger.info("Wrote generated schedule workbook: {}", xlsx_path)
        logger.info("Wrote generated schedule JSON: {}", json_path)


def _log(message: str) -> None:
    """Log a schedule generator message."""
    logger.info(message)


if __name__ == "__main__":
    main()
