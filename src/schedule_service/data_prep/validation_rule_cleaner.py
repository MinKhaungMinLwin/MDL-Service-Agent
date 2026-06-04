"""Clean validation_rule.csv — encoding and whitespace only.

Rules:
  - NEVER modify VT formula (Validation Time column).
  - NEVER modify Priority values.
  - Strip \xa0 and leading/trailing whitespace from all text columns.
  - Item: replace embedded \n with space (e.g. "Chemical\nDosing System").
  - Item: if value is only whitespace/\xa0 after strip, normalize to "".
  - MDL Document Keyword: when \n present, keep the part before \n as the
    keyword (parenthetical notes after \n are not matching terms).
    Exception: if the part before \n is empty, use the part after \n.
  - Validation Time: kept verbatim — vt_parser handles multi-line formulas.
  - All changes are reported in the XLSX diff sheet and the JSON report.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

DEFAULT_INPUT = Path("data/schedule_service/raw/validation_rule.csv")
DEFAULT_OUTPUT_DIR = Path("data/schedule_service/raw")
DEFAULT_OUTPUT_STEM = "validation_rule_clean"

# Columns that must NEVER be modified
_READONLY_COLS = {"Validation Time"}


@dataclass
class ChangeRecord:
    row_num: int
    column: str
    before: str
    after: str
    reason: str


def clean_validation_rules(
    input_path: Path = DEFAULT_INPUT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    output_stem: str = DEFAULT_OUTPUT_STEM,
) -> tuple[Path, Path, Path]:
    """Clean validation_rule.csv and write CSV + XLSX + JSON report.

    Returns (csv_path, xlsx_path, report_path).
    """
    input_path = input_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Reading: {}", input_path)
    with open(input_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        fieldnames = reader.fieldnames or []
        raw_rows: list[dict[str, str]] = list(reader)

    logger.info("Loaded {} rows, {} columns", len(raw_rows), len(fieldnames))

    cleaned_rows: list[dict[str, str]] = []
    changes: list[ChangeRecord] = []

    for row_idx, raw in enumerate(raw_rows, start=2):  # row 1 = header
        cleaned: dict[str, str] = {}
        for col in fieldnames:
            original = raw.get(col, "")
            if col in _READONLY_COLS:
                cleaned[col] = original
                continue

            if col == "MDL Document Keyword":
                value, reason = _clean_keyword(original)
            elif col == "Item":
                value, reason = _clean_item(original)
            else:
                value, reason = _clean_generic(original)

            cleaned[col] = value
            if value != original:
                changes.append(ChangeRecord(
                    row_num=row_idx,
                    column=col,
                    before=original,
                    after=value,
                    reason=reason,
                ))
        cleaned_rows.append(cleaned)

    logger.info("Found {} cells changed", len(changes))

    csv_path = output_dir / f"{output_stem}.csv"
    xlsx_path = output_dir / f"{output_stem}.xlsx"
    report_path = output_dir / f"{output_stem}_report.json"

    _write_csv(csv_path, fieldnames, cleaned_rows)
    _write_xlsx(xlsx_path, fieldnames, raw_rows, cleaned_rows, changes, input_path)
    _write_report(report_path, input_path, len(raw_rows), changes)

    logger.info("Cleaned CSV  → {}", csv_path)
    logger.info("Diff XLSX    → {}", xlsx_path)
    logger.info("JSON report  → {}", report_path)
    return csv_path, xlsx_path, report_path


# ---------------------------------------------------------------------------
# Per-column cleaning functions
# ---------------------------------------------------------------------------

def _clean_keyword(value: str) -> tuple[str, str]:
    """Clean MDL Document Keyword: strip whitespace/xa0, keep only main part before \\n."""
    if "\n" in value:
        parts = value.split("\n", 1)
        main = _strip_noise(parts[0])
        note = _strip_noise(parts[1])
        # If main content is empty, promote the note
        result = main if main else note
        return result, "stripped \\xa0/spaces; truncated at \\n (removed parenthetical note)"
    result = _strip_noise(value)
    if result != value:
        return result, "stripped \\xa0/leading/trailing whitespace"
    return value, ""


def _clean_item(value: str) -> tuple[str, str]:
    """Clean Item: replace embedded \\n with space, strip noise, \xa0-only → empty."""
    if "\n" in value:
        # "Chemical\nDosing System" → "Chemical Dosing System"
        joined = value.replace("\n", " ")
        result = _strip_noise(joined)
        return result, "replaced embedded \\n with space"
    result = _strip_noise(value)
    if result != value:
        return result, "stripped \\xa0/leading/trailing whitespace"
    return value, ""


def _clean_generic(value: str) -> tuple[str, str]:
    """Strip \xa0 and leading/trailing whitespace."""
    result = _strip_noise(value)
    if result != value:
        return result, "stripped \\xa0/leading/trailing whitespace"
    return value, ""


def _strip_noise(value: str) -> str:
    """Replace non-breaking spaces and strip whitespace."""
    cleaned = value.replace("\xa0", " ")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)  # collapse multiple spaces
    cleaned = cleaned.strip()
    return cleaned


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def _write_xlsx(
    path: Path,
    fieldnames: list[str],
    raw_rows: list[dict[str, str]],
    cleaned_rows: list[dict[str, str]],
    changes: list[ChangeRecord],
    input_path: Path,
) -> None:
    wb = Workbook()

    # --- Summary sheet ---
    summary = wb.active
    summary.title = "Summary"
    summary.append(["Field", "Value"])
    summary.append(["Source file", str(input_path)])
    summary.append(["Total rows", len(raw_rows)])
    summary.append(["Cells changed", len(changes)])
    summary.append(["Generated at", datetime.now().isoformat(timespec="seconds")])
    summary.append([])
    summary.append(["NEVER modified columns", "Validation Time"])
    summary.append(["Cleaning rules", ""])
    for note in [
        "Item: \\n → space, \\xa0 → empty",
        "MDL Document Keyword: truncate at \\n (keep part before); strip whitespace",
        "All other text cols: strip \\xa0 and leading/trailing spaces",
        "Validation Time: untouched (multi-line VT formulas kept as-is)",
    ]:
        summary.append(["", note])
    _fmt_sheet(summary)

    # --- Changes sheet ---
    diff = wb.create_sheet("Changes")
    diff.append(["Row", "Column", "Before", "After", "Reason"])
    for c in changes:
        diff.append([c.row_num, c.column, c.before, c.after, c.reason])
    _fmt_sheet(diff)
    diff.freeze_panes = "A2"
    diff.auto_filter.ref = diff.dimensions

    # --- Cleaned data sheet ---
    data_sheet = wb.create_sheet("Cleaned Rules")
    data_sheet.append(fieldnames)
    for row in cleaned_rows:
        data_sheet.append([row.get(col, "") for col in fieldnames])
    _fmt_sheet(data_sheet)
    data_sheet.freeze_panes = "A2"
    data_sheet.auto_filter.ref = data_sheet.dimensions

    wb.save(path)


def _write_report(path: Path, input_path: Path, total_rows: int, changes: list[ChangeRecord]) -> None:
    by_column: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for c in changes:
        by_column[c.column] = by_column.get(c.column, 0) + 1
        by_reason[c.reason] = by_reason.get(c.reason, 0) + 1

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(input_path),
        "total_rows": total_rows,
        "total_cells_changed": len(changes),
        "changes_by_column": by_column,
        "changes_by_reason": by_reason,
        "changes": [
            {"row": c.row_num, "column": c.column, "before": c.before, "after": c.after, "reason": c.reason}
            for c in changes
        ],
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt_sheet(ws: Any) -> None:
    fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
    for col_cells in ws.columns:
        letter = get_column_letter(col_cells[0].column)
        max_len = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells[:300])
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 80)


def main() -> None:
    """Run the validation rule cleaner CLI."""
    parser = argparse.ArgumentParser(description="Clean validation_rule.csv (encoding/whitespace only).")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default=DEFAULT_OUTPUT_STEM)
    args = parser.parse_args()

    csv_path, xlsx_path, report_path = clean_validation_rules(args.input, args.output_dir, args.output_stem)
    logger.info("Cleaned CSV  → {}", csv_path)
    logger.info("Diff XLSX    → {}", xlsx_path)
    logger.info("JSON report  → {}", report_path)


if __name__ == "__main__":
    main()
