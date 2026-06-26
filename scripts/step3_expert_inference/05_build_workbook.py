"""
Step 3 pipeline - script 5/5

Assembles the final 3-sheet workbook (ITB_EBS_List, Matched_Document_List,
Expert_Inferred_Documents) from step1/step2 (repo root) and the
expert_inferred_documents.csv produced by 04_select_and_rationale.py.
Applies basic formatting: bold header row, frozen header, autofilter,
wrapped text, and amber highlighting on rows flagged for review.

Usage:
    python 05_build_workbook.py

Inputs:
    step1_itb_ebs_list.csv             (repo root)
    step2_matched_documents.csv        (repo root)
    expert_inferred_documents.csv      (same dir as this script)
Output:
    R&N_ITB_EBS_MDL_Match_Final.xlsx   (repo root)
"""
import os
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.dirname(__file__)

# See note in 02_gap_analysis.py: tracked, reproducible equivalents of the
# original step1/step2 working files.
STEP1 = os.path.join(REPO_ROOT, "R&N_ITB_EBS_MDL_Match_Final_ITB_EBS_List.csv")
STEP2 = os.path.join(REPO_ROOT, "R&N_ITB_EBS_MDL_Match_Final_Matched_Document_List.csv")
STEP3 = os.path.join(OUT_DIR, "expert_inferred_documents.csv")
OUT_XLSX = os.path.join(REPO_ROOT, "R&N_ITB_EBS_MDL_Match_Final.xlsx")

HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
REVIEW_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
WRAP = Alignment(wrap_text=True, vertical="top")


def write_sheet(wb, name, df, review_col=None, review_value=None, max_col_width=60):
    ws = wb.create_sheet(name)
    ws.append(list(df.columns))
    for c in range(1, len(df.columns) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
    for _, row in df.iterrows():
        ws.append(list(row))

    review_idx = None
    if review_col and review_col in df.columns:
        review_idx = list(df.columns).index(review_col) + 1
    for r in range(2, ws.max_row + 1):
        is_review = False
        if review_idx:
            val = ws.cell(row=r, column=review_idx).value
            if val and review_value in str(val):
                is_review = True
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=c)
            cell.alignment = WRAP
            if is_review:
                cell.fill = REVIEW_FILL

    for c, col_name in enumerate(df.columns, start=1):
        try:
            sample_len = df[col_name].astype(str).str.len().quantile(0.5)
        except Exception:
            sample_len = 20
        width = min(max(12, sample_len * 0.9), max_col_width)
        ws.column_dimensions[get_column_letter(c)].width = width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def main():
    step1 = pd.read_csv(STEP1, dtype=str)
    step2 = pd.read_csv(STEP2, dtype=str)
    step3 = pd.read_csv(STEP3, dtype=str)

    wb = Workbook()
    wb.remove(wb.active)

    write_sheet(wb, "ITB_EBS_List", step1, review_col="Review Status", review_value="Review Required")
    write_sheet(wb, "Matched_Document_List", step2, review_col="Recommendation", review_value="Review")
    write_sheet(wb, "Expert_Inferred_Documents", step3, review_col="Review Status", review_value="Expert Inference")

    wb.save(OUT_XLSX)
    print(f"Workbook saved: {OUT_XLSX}")
    print(f"Sheet1 rows: {len(step1)} | Sheet2 rows: {len(step2)} | Sheet3 rows: {len(step3)}")


if __name__ == "__main__":
    main()
