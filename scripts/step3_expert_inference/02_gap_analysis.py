"""
Step 3 pipeline - script 2/5

For every Equipment/Building/System family extracted in Step 1
(step1_itb_ebs_list.csv), finds the full candidate document pool from the
Integrated MDL master catalog, subtracts anything already matched in Step 2
(step2_matched_documents.csv), and buckets the remaining candidates by
document-type class (Spec/DataSheet, Drawing/GA, Calculation, Manual/O&M,
List/Schedule, Test/Commissioning, Other).

Join-key rule (non-obvious from column names alone):
  - Category == "Equipment": LV1 == "Equipment" (literal), LV2 == the actual
    equipment family name. Join key is LV2.
  - Category == "Building": LV1 == "Building" (literal), LV2 == the actual
    building name. Join key is LV2.
  - Category == "System": LV1 == the actual system name, LV2 is usually
    blank. Join key is LV1.

Usage:
    python 02_gap_analysis.py

Inputs (repo root unless noted):
    step1_itb_ebs_list.csv
    step2_matched_documents.csv
    integrated_mdl.csv   (output of 01_convert_mdl_to_csv.py, same dir as this script)
Outputs (written next to this script):
    family_gap_analysis.csv   - one row per (JoinKey, candidate document)
    family_summary.csv        - one row per JoinKey with bucket coverage summary
"""
import os
import re
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.dirname(__file__)

# NOTE: step1_itb_ebs_list.csv / step2_matched_documents.csv were the
# original working-directory file names used during development, but they
# were never committed to git and can disappear from disk between sessions.
# The committed, reproducible source of the same data is the per-sheet CSV
# export of the final workbook, which IS tracked in the repo.
STEP1 = os.path.join(REPO_ROOT, "R&N_ITB_EBS_MDL_Match_Final_ITB_EBS_List.csv")
STEP2 = os.path.join(REPO_ROOT, "R&N_ITB_EBS_MDL_Match_Final_Matched_Document_List.csv")
MDL_CSV = os.path.join(OUT_DIR, "integrated_mdl.csv")


def normalize(s):
    if pd.isna(s):
        return ""
    s = str(s).lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip("().,; ")


def step1_joinkey(row):
    return row["LV2"] if row["Category"] in ("Equipment", "Building") else row["LV1"]


def step2_joinkey(row):
    return row["LV2"] if row["Matched Category"] in ("Equipment", "Building") else row["LV1"]


def bucket_doc_type(doc_type):
    dt = str(doc_type).lower()
    if any(k in dt for k in ["technical specification", "data sheet", "technical data sheet"]):
        return "SPEC_DATASHEET"
    if any(k in dt for k in ["general arrangement", "layout drawing", "outline drawing",
                              "schematic diagram", "architectural drawing", "arrangement drawing",
                              "wiring diagram", "p & id", "p&id"]):
        return "DRAWING_GA"
    if any(k in dt for k in ["design calculation", "sizing calculation", "calculation"]):
        return "CALCULATION"
    if any(k in dt for k in ["operation & maintenance", "o & m", "erection manual", "installation manual", "manual"]):
        return "MANUAL_OM"
    if any(k in dt for k in ["equipment list", "material requisition", "cable schedule", "instrument list", "list", "schedule"]):
        return "LIST_SCHEDULE"
    if any(k in dt for k in ["test procedure", "commissioning", "fat report", "tbe", "test"]):
        return "TEST_COMMISSIONING"
    return "OTHER"


def main():
    step1 = pd.read_csv(STEP1, dtype=str)
    step2 = pd.read_csv(STEP2, dtype=str)
    mdl = pd.read_csv(MDL_CSV, dtype=str)

    mdl["L1_norm"] = mdl["System (L1)"].apply(normalize)
    mdl["L2_norm"] = mdl["Sub-System / Area (L2)"].apply(normalize)
    mdl["Title_norm"] = mdl["Standardized Document Title"].apply(normalize)
    mdl["Bucket"] = mdl["Document Type"].apply(bucket_doc_type)

    step1["JoinKeyRaw"] = step1.apply(step1_joinkey, axis=1)
    step2["JoinKeyRaw"] = step2.apply(step2_joinkey, axis=1)

    distinct_keys = sorted(set(normalize(k) for k in step1["JoinKeyRaw"].dropna()))
    print(f"Distinct JoinKeys (non-alias-split) from step1: {len(distinct_keys)}")

    excluded_pairs = set()
    for _, r in step2.iterrows():
        excluded_pairs.add((normalize(r["JoinKeyRaw"]), normalize(r["Standardized Document Title"])))

    cat_by_key = {}
    for _, row in step1.iterrows():
        k = normalize(row["JoinKeyRaw"])
        if k and k not in cat_by_key:
            cat_by_key[k] = row["Category"]

    gap_rows = []
    summary_rows = []
    for key, cat in cat_by_key.items():
        pool = mdl[(mdl["L1_norm"] == key) | (mdl["L2_norm"] == key)].copy()
        if len(pool) > 0:
            pool = pool[~pool.apply(lambda r: (key, r["Title_norm"]) in excluded_pairs, axis=1)]

        covered = set()
        if len(pool) > 0:
            matched_titles_for_key = step2[step2["JoinKeyRaw"].apply(normalize) == key]["Standardized Document Title"]
            for t in matched_titles_for_key:
                covered.add(bucket_doc_type(t))

        bucket_counts = {}
        if len(pool) > 0:
            for bucket, grp in pool.groupby("Bucket"):
                bucket_counts[bucket] = grp["Standardized Document Title"].nunique()
                for _, r in grp.drop_duplicates(subset=["Standardized Document Title"]).iterrows():
                    gap_rows.append({
                        "JoinKey": key,
                        "Category": cat,
                        "Bucket": bucket,
                        "Standardized Document Title": r["Standardized Document Title"],
                        "Document Type": r["Document Type"],
                        "Source Projects": r["Source Projects"],
                        "Already_Covered_Buckets_In_Step2": ",".join(sorted(covered)),
                        "Candidate_Count_For_This_Bucket": bucket_counts[bucket],
                    })

        gap_buckets = [b for b in bucket_counts if b not in covered and b != "OTHER"]
        summary_rows.append({
            "JoinKey": key,
            "Category": cat,
            "Total_MDL_Candidates_After_Exclusion": len(pool),
            "Step2_Matched_Count": int((step2["JoinKeyRaw"].apply(normalize) == key).sum()),
            "Buckets_Covered_In_Step2": ",".join(sorted(covered)),
            "Buckets_With_Gap_And_Candidates_Available": ",".join(sorted(gap_buckets)),
        })

    pd.DataFrame(gap_rows).to_csv(os.path.join(OUT_DIR, "family_gap_analysis.csv"), index=False)
    pd.DataFrame(summary_rows).to_csv(os.path.join(OUT_DIR, "family_summary.csv"), index=False)
    print(f"family_gap_analysis.csv: {len(gap_rows)} rows")
    print(f"family_summary.csv: {len(summary_rows)} rows")


if __name__ == "__main__":
    main()
