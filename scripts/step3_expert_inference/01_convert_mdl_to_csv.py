"""
Step 3 pipeline - script 1/5

Converts the "Integrated MDL" sheet of vendor_package_integrated_mdl_all.xlsx
into a clean CSV for downstream scripting. Reads everything as strings to
avoid pandas mangling numeric-looking text (e.g. Source Standard Nos) or
coercing dates.

Usage:
    python 01_convert_mdl_to_csv.py

Input:
    vendor_package_integrated_mdl_all.xlsx  (repo root, sheet "Integrated MDL")
Output:
    integrated_mdl.csv  (written next to this script)
"""
import os
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.dirname(__file__)

XLSX_PATH = os.path.join(REPO_ROOT, "vendor_package_integrated_mdl_all.xlsx")
SHEET_NAME = "Integrated MDL"
OUT_CSV = os.path.join(OUT_DIR, "integrated_mdl.csv")


def main():
    df = pd.read_excel(XLSX_PATH, sheet_name=SHEET_NAME, dtype=str, engine="openpyxl")
    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {len(df)} rows x {len(df.columns)} cols to {OUT_CSV}")
    print("Columns:", list(df.columns))


if __name__ == "__main__":
    main()
