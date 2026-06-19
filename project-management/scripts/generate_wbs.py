#!/usr/bin/env python3
"""Generate project-management/content/wbs.html from MDL progress Excel sheet."""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

DEFAULT_EXCEL = Path("/Users/eric/Downloads/MDL 진행 현황 .xlsx")
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "content" / "ko" / "wbs.md"
SHEET_NAME = "현재"

# Table layout (1-based row/col indices)
ROW_TITLE = 2
ROW_PROGRESS = 4
ROW_NOTE_START = 5
ROW_NOTE_END = 9
ROW_MONTH_HEADER = 10
ROW_WEEK_HEADER = 11
DATA_ROW_START = 12
DATA_ROW_END = 37
COL_L1 = 2  # B
COL_L2 = 3  # C
COL_TASK = 4  # D
COL_STATUS = 5  # E
COL_TIMELINE_START = 6  # F
COL_TIMELINE_END = 36  # AJ

# First timeline column of each month (row 10 merge min_col)
MONTH_START_COLS = [6, 11, 15, 19, 24, 28, 33]


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u200b", "").strip()
    return text


def build_merge_maps(ws: openpyxl.worksheet.worksheet.Worksheet) -> tuple[dict[tuple[int, int], tuple[int, int]], set[tuple[int, int]]]:
    """Return anchor merges (rowspan, colspan) and covered cell coordinates."""
    anchors: dict[tuple[int, int], tuple[int, int]] = {}
    covered: set[tuple[int, int]] = set()
    for merged in ws.merged_cells.ranges:
        rs = merged.max_row - merged.min_row + 1
        cs = merged.max_col - merged.min_col + 1
        anchors[(merged.min_row, merged.min_col)] = (rs, cs)
        for r in range(merged.min_row, merged.max_row + 1):
            for c in range(merged.min_col, merged.max_col + 1):
                if (r, c) != (merged.min_row, merged.min_col):
                    covered.add((r, c))
    return anchors, covered


def cell_value(ws: openpyxl.worksheet.worksheet.Worksheet, r: int, c: int, covered: set[tuple[int, int]], anchors: dict) -> str:
    if (r, c) in covered:
        for (mr, mc), (rs, cs) in anchors.items():
            if mr <= r <= mr + rs - 1 and mc <= c <= mc + cs - 1:
                return clean_text(ws.cell(mr, mc).value)
        return ""
    return clean_text(ws.cell(r, c).value)


def timeline_class(cell: openpyxl.cell.cell.Cell) -> str:
    fill = cell.fill
    if not fill or not fill.fgColor or not fill.patternType:
        return ""
    fg = fill.fgColor
    if fg.type == "rgb":
        rgb = (fg.rgb or "").upper()
        if not rgb or rgb in ("00000000", "FFFFFFFF"):
            return ""
        if "002060" in rgb:
            return "tl-done"
        if rgb in ("FFBFBFBF", "FFA6A6A6"):
            return "tl-planned"
        return ""
    if fg.theme == 9:
        return "tl-progress"
    if fg.theme == 0:
        return "tl-planned"
    return ""


def status_badge(status: str) -> str:
    status = clean_text(status)
    css = {
        "완료": "status-done",
        "진행중": "status-progress",
        "진행예정": "status-planned",
    }.get(status, "status-planned")
    return f'<span class="status-badge {css}">{html.escape(status)}</span>'


def month_spans(ws: openpyxl.worksheet.worksheet.Worksheet) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for merged in ws.merged_cells.ranges:
        if merged.min_row == ROW_MONTH_HEADER and merged.max_row == ROW_MONTH_HEADER:
            label = clean_text(ws.cell(merged.min_row, merged.min_col).value)
            colspan = merged.max_col - merged.min_col + 1
            spans.append((merged.min_col, colspan, label))
    spans.sort(key=lambda x: x[0])
    return spans


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def generate_html(ws: openpyxl.worksheet.worksheet.Worksheet) -> str:
    anchors, covered = build_merge_maps(ws)

    title = clean_text(ws.cell(ROW_TITLE, COL_L1).value)
    progress_raw = ws.cell(ROW_PROGRESS, 3).value
    if isinstance(progress_raw, (int, float)):
        progress_pct = int(round(float(progress_raw) * 100))
    else:
        m = re.search(r"(\d+)", clean_text(progress_raw))
        progress_pct = int(m.group(1)) if m else 0

    notes = [clean_text(ws.cell(r, COL_L1).value) for r in range(ROW_NOTE_START, ROW_NOTE_END + 1)]
    notes = [n for n in notes if n]

    parts: list[str] = []
    parts.append('<header class="page-header">')
    parts.append("        <h1>진행현황 (WBS)</h1>")
    parts.append(f"        <p>{esc(title)}</p>")
    parts.append('        <div class="meta-row">')
    parts.append(f'          <span class="meta-pill"><strong>전체 진행률</strong> {progress_pct}%</span>')
    parts.append("        </div>")
    parts.append('        <div class="progress-bar progress-bar-lg" style="margin-top:1rem;">')
    parts.append(f'          <div class="progress-fill" style="width:{progress_pct}%"></div>')
    parts.append("        </div>")
    parts.append("      </header>")
    parts.append("")
    parts.append("      <section>")
    for i, note in enumerate(notes):
        cls = "note-text" if i == 0 else "note-text note-sub"
        parts.append(f'        <p class="{cls}">{esc(note)}</p>')
    parts.append('        <div class="legend-row">')
    parts.append('          <span class="legend-item"><span class="tl-cell tl-done legend-swatch"></span> 완료</span>')
    parts.append('          <span class="legend-item"><span class="tl-cell tl-progress legend-swatch"></span> 진행 중</span>')
    parts.append('          <span class="legend-item"><span class="tl-cell tl-planned legend-swatch"></span> 진행 예정</span>')
    parts.append("        </div>")
    parts.append("      </section>")
    parts.append("")
    parts.append("      <section>")
    parts.append("        <h2>WBS 일정표</h2>")
    parts.append('        <div class="table-scroll"><table class="wbs-table"><thead>')

    # Header row 1
    parts.append("<tr>")
    # B10:C11 merged in Excel → single header spanning L1+L2 columns
    parts.append('<th rowspan="2" colspan="2" class="col-b">구분</th>')
    parts.append('<th rowspan="2" class="col-task">세부 업무</th>')
    parts.append('<th rowspan="2" class="status-col">진행상태</th>')
    for min_col, colspan, label in month_spans(ws):
        classes = ["month-header"]
        if min_col == COL_TIMELINE_START:
            classes.append("timeline-start")
        else:
            classes.append("month-start")
        parts.append(f'<th colspan="{colspan}" class="{" ".join(classes)}">{esc(label)}</th>')
    parts.append("</tr>")

    # Header row 2 — week labels
    parts.append("<tr>")
    for col in range(COL_TIMELINE_START, COL_TIMELINE_END + 1):
        week = clean_text(ws.cell(ROW_WEEK_HEADER, col).value)
        classes = ["week-col"]
        if col in MONTH_START_COLS:
            classes.append("month-start")
        parts.append(f'<th class="{" ".join(classes)}">{esc(week)}</th>')
    parts.append("</tr></thead><tbody>")

    for r in range(DATA_ROW_START, DATA_ROW_END + 1):
        parts.append("<tr>")
        for col in (COL_L1, COL_L2, COL_TASK, COL_STATUS):
            if (r, col) in covered:
                continue
            val = cell_value(ws, r, col, covered, anchors)
            if col == COL_L1:
                rs, cs = anchors.get((r, col), (1, 1))
                classes = ["l1-cell"]
                if cs >= 2:
                    classes.append("l1-merged")
                span = ""
                if rs > 1:
                    span += f' rowspan="{rs}"'
                if cs > 1:
                    span += f' colspan="{cs}"'
                parts.append(f'<td{span} class="{" ".join(classes)}">{esc(val)}</td>')
            elif col == COL_L2:
                rs, cs = anchors.get((r, col), (1, 1))
                span = f' rowspan="{rs}"' if rs > 1 else ""
                parts.append(f'<td{span} class="l2-cell">{esc(val)}</td>')
            elif col == COL_TASK:
                parts.append(f'<td class="task-cell">{esc(val)}</td>')
            elif col == COL_STATUS:
                parts.append(f'<td class="status-col">{status_badge(val)}</td>')

        for col in range(COL_TIMELINE_START, COL_TIMELINE_END + 1):
            tl = timeline_class(ws.cell(r, col))
            classes = ["tl-cell"]
            if tl:
                classes.append(tl)
            if col in MONTH_START_COLS:
                classes.append("month-start")
            parts.append(f'<td class="{" ".join(classes)}"></td>')
        parts.append("</tr>")

    parts.append("</tbody></table></div>")
    parts.append("      </section>")
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate wbs.html from MDL progress Excel.")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL, help="Path to .xlsx file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output wbs.html path")
    parser.add_argument("--sheet", default=SHEET_NAME, help="Worksheet name")
    args = parser.parse_args()

    if not args.excel.is_file():
        print(f"Excel not found: {args.excel}", file=sys.stderr)
        return 1

    wb = openpyxl.load_workbook(args.excel, data_only=True)
    if args.sheet not in wb.sheetnames:
        print(f"Sheet {args.sheet!r} not found. Available: {wb.sheetnames}", file=sys.stderr)
        return 1

    ws = wb[args.sheet]
    # Styles (fills) require data_only=False — reload for timeline colors
    wb_styles = openpyxl.load_workbook(args.excel, data_only=False)
    ws = wb_styles[args.sheet]

    out_html = generate_html(ws)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    md = f"<!-- html -->\n\n{out_html}\n"
    args.output.write_text(md, encoding="utf-8")
    print(f"Wrote {args.output} ({len(md)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
