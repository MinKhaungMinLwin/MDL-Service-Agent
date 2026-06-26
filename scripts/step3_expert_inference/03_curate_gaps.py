"""
Step 3 pipeline - script 3/5

Script 2 computes gaps keyed by the raw JoinKey from step1, which for a few
Building rows is a comma-joined alias list (e.g. "CCB, CENTRAL CONTROL
BUILDING, Control Center, ...") that never normalize-matches any single MDL
System(L1)/Sub-System(L2) value, so those rows show 0 candidates in
family_summary.csv. This script splits those compound keys into individual
aliases and recomputes the candidate pool + gap buckets per alias directly
against the MDL and Step 2 exclusion set. It also drops the two mega-generic
"junk-drawer" families (General, Plant General System) which are too broad
to safely infer specific documents from, and drops the OTHER bucket as
non-actionable noise.

Usage:
    python 03_curate_gaps.py

Inputs (repo root unless noted):
    step1_itb_ebs_list.csv
    step2_matched_documents.csv
    integrated_mdl.csv          (same dir as this script)
    family_gap_analysis.csv     (output of 02_gap_analysis.py, not directly
                                  reused here, but kept as a human-readable
                                  intermediate artifact)
    family_summary.csv          (same)
Output:
    curated_gap_records.json   - list of {norm_key, Category, Bucket,
                                  candidates: [...], candidate_count}
"""
import os
import re
import json
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.dirname(__file__)

# See note in 02_gap_analysis.py: these are the tracked, reproducible
# equivalents of the original step1/step2 working files.
STEP1 = os.path.join(REPO_ROOT, "R&N_ITB_EBS_MDL_Match_Final_ITB_EBS_List.csv")
STEP2 = os.path.join(REPO_ROOT, "R&N_ITB_EBS_MDL_Match_Final_Matched_Document_List.csv")
MDL_CSV = os.path.join(OUT_DIR, "integrated_mdl.csv")

EXCLUDE_FAMILIES_DISPLAY = ["General", "Plant General System"]


def normalize(s):
    if pd.isna(s):
        return ""
    s = str(s).lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip("().,; ")


def joinkey_aliases(row, lv1_col="LV1", lv2_col="LV2", cat_col="Category"):
    cat = row[cat_col]
    key_field = row[lv2_col] if cat in ("Equipment", "Building") else row[lv1_col]
    if pd.isna(key_field):
        return []
    return [p.strip() for p in str(key_field).split(",") if p.strip()]


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

    cat_lookup = {}
    for _, row in step1.iterrows():
        for alias in joinkey_aliases(row):
            norm = normalize(alias)
            if norm and norm not in cat_lookup:
                cat_lookup[norm] = row["Category"]
    print(f"Distinct normalized alias JoinKeys after split: {len(cat_lookup)}")

    def step2_joinkey(row):
        return row["LV2"] if row["Matched Category"] in ("Equipment", "Building") else row["LV1"]
    step2["JoinKeyRaw"] = step2.apply(step2_joinkey, axis=1)

    excluded_pairs = set()
    for _, r in step2.iterrows():
        for alias in [a.strip() for a in str(r["JoinKeyRaw"]).split(",") if a.strip()]:
            excluded_pairs.add((normalize(alias), normalize(r["Standardized Document Title"])))

    records = []
    for norm_key, cat in cat_lookup.items():
        pool = mdl[(mdl["L1_norm"] == norm_key) | (mdl["L2_norm"] == norm_key)].copy()
        if len(pool) == 0:
            continue
        pool = pool[~pool.apply(lambda r: (norm_key, r["Title_norm"]) in excluded_pairs, axis=1)]
        if len(pool) == 0:
            continue

        covered = set()
        for _, r in step2.iterrows():
            aliases = [normalize(a.strip()) for a in str(r["JoinKeyRaw"]).split(",") if a.strip()]
            if norm_key in aliases:
                covered.add(bucket_doc_type(str(r["Standardized Document Title"]).lower()))

        for bucket, grp in pool.groupby("Bucket"):
            if bucket in covered or bucket == "OTHER":
                continue
            records.append({
                "norm_key": norm_key,
                "Category": cat,
                "Bucket": bucket,
                "candidates": grp[["Standardized Document Title", "Document Type", "Source Projects"]]
                    .drop_duplicates(subset=["Standardized Document Title"]).to_dict("records"),
                "candidate_count": grp["Standardized Document Title"].nunique(),
            })

    print(f"Gap records (key x bucket, excluding OTHER): {len(records)}")

    exclude_norm = {normalize(x) for x in EXCLUDE_FAMILIES_DISPLAY}
    records = [r for r in records if r["norm_key"] not in exclude_norm]
    print(f"After excluding generic junk-drawer families: {len(records)}")

    with open(os.path.join(OUT_DIR, "curated_gap_records.json"), "w") as f:
        json.dump(records, f, indent=2)

    fam_count = len(set(r["norm_key"] for r in records))
    print(f"Distinct families with at least one actionable gap: {fam_count}")
    print("Wrote curated_gap_records.json")


if __name__ == "__main__":
    main()
