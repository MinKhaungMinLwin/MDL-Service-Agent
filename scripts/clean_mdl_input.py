"""Clean and enrich MDL classified CSV files before schedule generation.

The cleaner is intentionally conservative:
- writes a new CSV and never mutates the source file;
- updates the standard schedule input columns in the output file so it can be
  passed directly to /schedule/generate;
- keeps *_original columns plus audit fields for review.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from schedule_service.generate.activity.matcher import _scope_keys as activity_scope_keys
from schedule_service.normalizer import (
    extract_deliverable,
    normalize_deliverable,
    normalize_equipment,
    refine_deliverable_with_title,
)

STANDARD_FIELDS = ("Equipment", "System", "Building", "Deliverable")
ORIGINAL_SUFFIX = "_original"

DELIVERABLE_ONLY_VALUES = {
    "arrangement",
    "calculation",
    "calculations",
    "data",
    "datasheet",
    "detail",
    "diagram",
    "drawing",
    "list",
    "manual",
    "plan",
    "procedure",
    "report",
    "schedule",
    "sheet",
    "specification",
    "study",
    "test",
}

GARBAGE_TITLES = {"", "s", "-", "nan", "none", "null"}

FIELD_BY_SCOPE: dict[str, tuple[str, str]] = {
    # Equipment/package level scopes.
    "acc": ("Equipment", "Air Cooled Condenser"),
    "bsedg": ("Equipment", "Blackstart Emergency Diesel Generator"),
    "crane_hoist": ("Equipment", "Crane & Hoist"),
    "dcs": ("Equipment", "DCS"),
    "fgp": ("Equipment", "Fuel Gas Package"),
    "gtg": ("Equipment", "Gas Turbine Generator"),
    "gsut_uat": ("Equipment", "GSUT/UAT Transformer"),
    "h2": ("Equipment", "Hydrogen System"),
    "hrsg": ("Equipment", "Heat Recovery Steam Generator"),
    "mv_lv": ("Equipment", "MV/LV Switchgear"),
    "n2": ("Equipment", "Nitrogen System"),
    "reserve_boiler": ("Equipment", "Reserve Boiler"),
    "stg": ("Equipment", "Steam Turbine & Generator"),
    "tank": ("Equipment", "Tank"),
    # System level scopes.
    "bop": ("System", "Balance of Plant"),
    "ccw": ("System", "Closed Cooling Water System"),
    "cems": ("System", "Continuous Emissions Monitoring System"),
    "compressed_air": ("System", "Compressed Air System"),
    "condensate": ("System", "Condensate System"),
    "dc_ups": ("System", "DC & UPS System"),
    "electrical": ("System", "Electrical System"),
    "feedwater": ("System", "Feedwater System"),
    "fire_fighting": ("System", "Fire Fighting System"),
    "hvac": ("System", "HVAC System"),
    "sampling": ("System", "Sampling System"),
    "service_water": ("System", "Service Water System"),
    "steam": ("System", "Steam System"),
    "wts": ("System", "Water Treatment System"),
}

BUILDING_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Central Control Building", ("CENTRAL CONTROL BUILDING", "CCR")),
    ("Water Treatment Building", ("WATER TREATMENT BUILDING",)),
    ("Local Electrical Building", ("LOCAL ELECTRICAL BUILDING", "LOCAL ELECTRICAL ROOM", "LEB")),
    ("Steam Turbine Building", ("STEAM TURBINE BUILDING", "ST BUILDING")),
    ("Administration & Social Building", ("ADMINISTRATION & SOCIAL BUILDING", "ADMINISTRATION BUILDING")),
    ("Fire Water Pump House", ("FIRE WATER PUMP HOUSE", "FIRE PUMP HOUSE")),
    ("Pipe Rack", ("PIPE RACK", "PIPERACK")),
    ("Workshop & Storage Building", ("WORKSHOP & STORAGE BUILDING", "WORKSHOP", "STORAGE BUILDING")),
    ("Air Compressor Shelter", ("AIR COMPRESSOR SHELTER",)),
    ("Chemical Dosing Shelter", ("CHEMICAL DOSING SHELTER",)),
    ("Security Building", ("SECURITY BUILDING", "MAIN GATE HOUSE", "SEARCH FACILITY", "VISITORS CENTRE")),
    ("Support Building", ("SUPPORT BUILDING",)),
)

PLANT_GENERAL_PATTERNS = (
    "DOCUMENT IDENTIFICATION",
    "EQUIPMENT AND SYSTEM IDENTIFICATION",
    "SITE PLAN",
    "PLOT PLAN",
    "HEAT BALANCE",
    "WATER BALANCE",
    "ABBREVIATION LIST",
    "NAME AND TAG PLATE",
    "DANGER SIGN",
    "UNDERGROUND PIPE MARKER",
    "MAINTAINABILITY STUDY",
    "CORROSION AND MATERIAL STUDY",
    "BUILDING RISK ASSESSMENT",
)


@dataclass
class CleanResult:
    row: dict[str, str]
    actions: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    fill_sources: list[str] = field(default_factory=list)
    confidence: float = 1.0
    scope_status: str = "unchanged"
    needs_review: bool = False


def clean_file(input_csv: Path, output_csv: Path, report_path: Path | None = None) -> dict[str, int]:
    """Clean one MDL classified CSV and write a feedable audited CSV."""
    rows = _read_rows(input_csv)
    cleaned = [clean_row(row) for row in rows]
    _write_rows(output_csv, rows, cleaned)
    summary = _summary(cleaned)
    if report_path:
        _write_report(report_path, input_csv, output_csv, summary, cleaned)
    return summary


def clean_row(row: dict[str, str]) -> CleanResult:
    """Return one cleaned row plus audit metadata."""
    result = CleanResult(row=dict(row))
    original = {field: _clean_cell(row.get(field, "")) for field in STANDARD_FIELDS}
    title = _clean_cell(row.get("Title", ""))
    others = _clean_cell(row.get("Others", ""))

    cleaned = dict(original)
    cleaned["Equipment"] = _canonical_equipment_value(cleaned["Equipment"])
    cleaned["System"] = _canonical_text_value(cleaned["System"])
    cleaned["Building"] = _canonical_building_value(cleaned["Building"])
    cleaned["Deliverable"] = _canonical_deliverable_value(cleaned["Deliverable"], title)

    if cleaned != original:
        result.actions.append("canonicalized_existing_fields")
        result.confidence = min(result.confidence, 0.95)

    _move_misplaced_deliverable_from_system(cleaned, result)
    _fill_building(cleaned, title, others, result)
    _fill_scope(cleaned, title, others, result)
    _fill_deliverable(cleaned, title, result)
    _mark_plant_general(cleaned, title, result)
    _mark_garbage_title(title, result)

    for field_name, value in cleaned.items():
        result.row[field_name] = value
        result.row[f"{field_name}{ORIGINAL_SUFFIX}"] = original[field_name]

    if result.conflicts:
        result.scope_status = "conflict"
        result.needs_review = True
        result.confidence = min(result.confidence, 0.35)
    elif result.scope_status == "unchanged" and result.actions:
        result.scope_status = "auto_cleaned"
    elif result.scope_status == "unchanged":
        result.scope_status = "ok"

    result.row["cleaning_actions"] = ";".join(result.actions)
    result.row["cleaning_confidence"] = f"{result.confidence:.2f}"
    result.row["scope_status"] = result.scope_status
    result.row["scope_fill_source"] = ";".join(dict.fromkeys(result.fill_sources))
    result.row["scope_conflict_reason"] = ";".join(result.conflicts)
    result.row["needs_human_review"] = "true" if result.needs_review else "false"
    return result


def _move_misplaced_deliverable_from_system(cleaned: dict[str, str], result: CleanResult) -> None:
    system = cleaned["System"]
    if not system:
        return
    normalized = system.casefold().strip()
    if normalized not in DELIVERABLE_ONLY_VALUES:
        return
    if not cleaned["Deliverable"]:
        cleaned["Deliverable"] = _canonical_deliverable_value(system, "")
        result.actions.append("moved_system_value_to_deliverable")
    else:
        result.actions.append("cleared_deliverable_value_from_system")
    cleaned["System"] = ""
    result.confidence = min(result.confidence, 0.9)


def _fill_building(cleaned: dict[str, str], title: str, others: str, result: CleanResult) -> None:
    detected = _detect_building(f"{title} {others}")
    if not detected:
        return
    if not cleaned["Building"]:
        cleaned["Building"] = detected
        result.actions.append("filled_building_from_title_or_others")
        result.fill_sources.append("building:title_or_others")
        result.confidence = min(result.confidence, 0.85)
    elif _norm(cleaned["Building"]) != _norm(detected):
        result.conflicts.append(f"building_conflict:{cleaned['Building']}!=detected:{detected}")


def _fill_scope(cleaned: dict[str, str], title: str, others: str, result: CleanResult) -> None:
    detected_scopes = activity_scope_keys(f"{title} {others}")
    if not detected_scopes:
        return
    for scope in detected_scopes:
        mapped = FIELD_BY_SCOPE.get(scope)
        if not mapped:
            continue
        field_name, canonical = mapped
        current = cleaned[field_name]
        current_structured_scopes = set(
            activity_scope_keys(" ".join(cleaned[field] for field in ("Equipment", "System", "Building")))
        )
        if (
            current_structured_scopes
            and scope not in current_structured_scopes
            and not _compatible_scope(scope, current_structured_scopes)
        ):
            result.conflicts.append(
                f"structured_scope_conflict:existing={','.join(sorted(current_structured_scopes))};detected={scope}"
            )
            continue
        if not current:
            cleaned[field_name] = canonical
            result.actions.append(f"filled_{field_name.lower()}_from_scope:{scope}")
            result.fill_sources.append(f"{field_name.lower()}:title_or_others")
            result.confidence = min(result.confidence, 0.8)
            continue
        current_scopes = set(activity_scope_keys(current))
        if current_scopes and scope not in current_scopes and not _compatible_scope(scope, current_scopes):
            result.conflicts.append(f"{field_name.lower()}_scope_conflict:{current}!=detected:{canonical}")


def _fill_deliverable(cleaned: dict[str, str], title: str, result: CleanResult) -> None:
    detected = _canonical_deliverable_value("", title)
    if not detected:
        return
    if not cleaned["Deliverable"]:
        cleaned["Deliverable"] = detected
        result.actions.append("filled_deliverable_from_title")
        result.fill_sources.append("deliverable:title")
        result.confidence = min(result.confidence, 0.85)


def _mark_plant_general(cleaned: dict[str, str], title: str, result: CleanResult) -> None:
    if cleaned["Equipment"] or cleaned["System"] or cleaned["Building"]:
        return
    upper = title.upper()
    if any(pattern in upper for pattern in PLANT_GENERAL_PATTERNS):
        cleaned["System"] = "Plant General System"
        result.actions.append("assigned_plant_general_scope")
        result.fill_sources.append("system:plant_general_title")
        result.scope_status = "plant_general"
        result.confidence = min(result.confidence, 0.75)


def _mark_garbage_title(title: str, result: CleanResult) -> None:
    if title.strip().casefold() in GARBAGE_TITLES or len(title.strip()) <= 1:
        result.actions.append("flagged_garbage_title")
        result.scope_status = "invalid_title"
        result.needs_review = True
        result.confidence = min(result.confidence, 0.2)


def _canonical_equipment_value(value: str) -> str:
    value = _choose_pipe_variant(value)
    return normalize_equipment(value)


def _canonical_building_value(value: str) -> str:
    value = _choose_pipe_variant(value)
    detected = _detect_building(value)
    return detected or _canonical_text_value(value)


def _canonical_deliverable_value(value: str, title: str) -> str:
    value = _choose_pipe_variant(value)
    refined = refine_deliverable_with_title(value, title)
    if not refined:
        refined = extract_deliverable(title)
    return normalize_deliverable(refined)


def _canonical_text_value(value: str) -> str:
    return _choose_pipe_variant(value)


def _choose_pipe_variant(value: str) -> str:
    cleaned = _clean_cell(value)
    if " | " not in cleaned:
        return cleaned
    parts = [_clean_cell(part) for part in cleaned.split("|") if _clean_cell(part)]
    if not parts:
        return ""
    normalized = [normalize_equipment(part) for part in parts]
    return max(normalized, key=lambda part: (len(part.split()), len(part)))


def _detect_building(text: str) -> str:
    upper = f" {text.upper()} "
    for canonical, patterns in BUILDING_PATTERNS:
        if any(_contains_phrase(upper, pattern) for pattern in patterns):
            return canonical
    return ""


def _compatible_scope(scope: str, current_scopes: set[str]) -> bool:
    compatible_groups = ({"acc", "condensate"},)
    return any(scope in group and current_scopes & group for group in compatible_groups)


def _contains_phrase(text: str, phrase: str) -> bool:
    return _norm(phrase) in _norm(text)


def _clean_cell(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\xa0", " ").strip()
    if text.casefold() in {"nan", "none", "null"}:
        return ""
    return " ".join(text.split())


def _norm(value: str) -> str:
    import re

    text = value.upper().replace("&", " AND")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_rows(input_path: Path, original_rows: list[dict[str, str]], cleaned: list[CleanResult]) -> None:
    base_fields = list(original_rows[0].keys()) if original_rows else []
    extra_fields = [f"{field}{ORIGINAL_SUFFIX}" for field in STANDARD_FIELDS] + [
        "cleaning_actions",
        "cleaning_confidence",
        "scope_status",
        "scope_fill_source",
        "scope_conflict_reason",
        "needs_human_review",
    ]
    fieldnames = list(dict.fromkeys([*base_fields, *extra_fields]))
    input_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result.row for result in cleaned)


def _summary(cleaned: list[CleanResult]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    counter["rows"] = len(cleaned)
    for result in cleaned:
        counter[f"scope_status:{result.row['scope_status']}"] += 1
        if result.row["needs_human_review"] == "true":
            counter["needs_human_review"] += 1
        for action in result.actions:
            counter[f"action:{action.split(':', 1)[0]}"] += 1
        if result.conflicts:
            counter["rows_with_conflict"] += 1
    return dict(counter)


def _write_report(
    path: Path,
    input_csv: Path,
    output_csv: Path,
    summary: dict[str, int],
    cleaned: list[CleanResult],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = summary.get("rows", 0) or 1
    status_lines = [
        (key.removeprefix("scope_status:"), value)
        for key, value in sorted(summary.items())
        if key.startswith("scope_status:")
    ]
    action_lines = [
        (key.removeprefix("action:"), value)
        for key, value in sorted(summary.items())
        if key.startswith("action:")
    ]
    review_samples = [r for r in cleaned if r.row["needs_human_review"] == "true"][:20]
    review_count = summary.get("needs_human_review", 0)
    row_count = summary.get("rows", 0)
    review_percent = review_count / rows * 100
    lines = [
        "# MDL Input Cleaning Report",
        "",
        f"Input: `{input_csv}`",
        f"Output: `{output_csv}`",
        f"Rows: **{row_count}**",
        f"Needs human review: **{review_count} / {row_count} ({review_percent:.2f}%)**",
        f"Rows with conflict: **{summary.get('rows_with_conflict', 0)}**",
        "",
        "## Scope Status",
        "",
        "| status | count | percent |",
        "|---|---:|---:|",
    ]
    lines.extend(f"| {status} | {count} | {count / rows * 100:.2f}% |" for status, count in status_lines)
    lines.extend(["", "## Actions", "", "| action | count |", "|---|---:|"])
    lines.extend(f"| {action} | {count} |" for action, count in action_lines)
    lines.extend(["", "## Review Samples", ""])
    if not review_samples:
        lines.append("No review samples.")
    else:
        lines.extend([
            "| document_no | title | reason |",
            "|---|---|---|",
        ])
        for result in review_samples:
            row = result.row
            reason = row.get("scope_conflict_reason") or row.get("cleaning_actions", "")
            lines.append(
                f"| {_md(row.get('Document No', ''))} | {_md(row.get('Title', ''))} | {_md(reason)} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean an MDL classified CSV before schedule generation.")
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="Output cleaned CSV path.")
    parser.add_argument("--report", type=Path, default=None, help="Optional markdown report path.")
    args = parser.parse_args()

    output_csv = args.out or args.input_csv.with_name(f"{args.input_csv.stem}_cleaned.csv")
    report_path = args.report or output_csv.with_suffix(".clean_report.md")
    summary = clean_file(args.input_csv, output_csv, report_path)
    print(f"Wrote cleaned CSV: {output_csv}")
    print(f"Wrote report: {report_path}")
    print(f"Rows: {summary.get('rows', 0)}")
    print(f"Needs human review: {summary.get('needs_human_review', 0)}")


if __name__ == "__main__":
    main()
