"""
Step 3 pipeline - script 4/5

For each (family, gap-bucket) record produced by 03_curate_gaps.py, selects
the single most relevant candidate document title (preferring titles that
contain a token from the family name, then the shortest/most generic title),
and generates an engineering rationale from a per-bucket template explaining
why the document is needed and why the ITB text didn't surface it directly.

Usage:
    python 04_select_and_rationale.py

Inputs:
    curated_gap_records.json   (output of 03_curate_gaps.py, same dir)
    step1_itb_ebs_list.csv     (repo root, used to recover a human-readable
                                 display name for each normalized family key)
Output:
    expert_inferred_documents.csv
"""
import os
import re
import json
import csv
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.dirname(__file__)

# See note in 02_gap_analysis.py: tracked, reproducible equivalent of step1.
STEP1 = os.path.join(REPO_ROOT, "R&N_ITB_EBS_MDL_Match_Final_ITB_EBS_List.csv")
RECORDS_JSON = os.path.join(OUT_DIR, "curated_gap_records.json")
OUT_CSV = os.path.join(OUT_DIR, "expert_inferred_documents.csv")

RATIONALE = {
    "SPEC_DATASHEET": (
        "The ITB defines a functional/performance requirement for {fam} but does not name a specific vendor "
        "Technical Specification or Data Sheet. EPC procurement and vendor bid evaluation require a baseline "
        "spec/data sheet to define ratings, materials, and acceptance criteria for {fam}, even though the ITB "
        "narrative never names the document itself."
    ),
    "DRAWING_GA": (
        "No General Arrangement / layout / schematic drawing for {fam} was matched from ITB text, because the "
        "ITB describes scope and performance, not drawing deliverables. A GA/layout/schematic drawing is a "
        "standard EPC interface-coordination deliverable needed to fix space, routing, and tie-in points for {fam}."
    ),
    "CALCULATION": (
        "{fam} requires a sizing/design/foundation calculation to support detailed engineering (loads, capacity, "
        "structural support), which is implied by the ITB's functional requirement but never explicitly requested "
        "as a calculation deliverable in the ITB text."
    ),
    "MANUAL_OM": (
        "An Operation & Maintenance or Erection Manual for {fam} is required for commissioning, handover, and "
        "O&M readiness; the ITB specifies the equipment/system scope but does not separately call out manuals "
        "as a deliverable."
    ),
    "LIST_SCHEDULE": (
        "A quantities/interface list or schedule (e.g. equipment list, cable schedule, material requisition) for "
        "{fam} is needed to track scope and interfaces across disciplines; the ITB narrative does not itemize "
        "this list-type deliverable even though the underlying scope is referenced."
    ),
    "TEST_COMMISSIONING": (
        "Factory acceptance / commissioning test documentation for {fam} is required to verify performance "
        "before handover; the ITB states the performance requirement but does not separately request the "
        "test-procedure deliverable."
    ),
}

BUCKET_TO_DOCTYPE_LABEL = {
    "SPEC_DATASHEET": "Technical Specification / Data Sheet",
    "DRAWING_GA": "General Arrangement / Layout / Schematic Drawing",
    "CALCULATION": "Design / Sizing / Foundation Calculation",
    "MANUAL_OM": "Operation & Maintenance / Erection Manual",
    "LIST_SCHEDULE": "Equipment List / Schedule / Material Requisition",
    "TEST_COMMISSIONING": "Test Procedure / Commissioning / FAT Report",
}


def normalize(s):
    if pd.isna(s):
        return ""
    s = str(s).lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip("().,; ")


def pick_best_candidate(fam_norm, candidates):
    fam_tokens = [t for t in re.split(r"[^a-z0-9]+", fam_norm) if len(t) > 2]

    def score(c):
        title_l = c["Standardized Document Title"].lower()
        contains_fam = any(tok in title_l for tok in fam_tokens)
        return (0 if contains_fam else 1, len(title_l))

    return sorted(candidates, key=score)[0]


def main():
    records = json.load(open(RECORDS_JSON))
    step1 = pd.read_csv(STEP1, dtype=str)

    display_name_map = {}
    for _, row in step1.iterrows():
        cat = row["Category"]
        field = row["LV2"] if cat in ("Equipment", "Building") else row["LV1"]
        if pd.isna(field):
            continue
        for alias in [a.strip() for a in str(field).split(",")]:
            if alias:
                display_name_map.setdefault(normalize(alias), alias)

    rows = []
    no = 1
    for r in records:
        fam_norm = r["norm_key"]
        cat = r["Category"]
        bucket = r["Bucket"]
        display_fam = display_name_map.get(fam_norm, fam_norm)
        best = pick_best_candidate(fam_norm, r["candidates"])
        title = best["Standardized Document Title"]
        doc_type = best["Document Type"]
        src = best["Source Projects"]
        rationale = RATIONALE[bucket].format(fam=display_fam)
        rows.append({
            "No": no,
            "Inferred Category": cat,
            "Related Equipment / Building / System": display_fam,
            "Recommended Document Title": title,
            "Standardized Document Title": title,
            "Source Project / Source MDL": src,
            "Why This Is Needed": rationale,
            "Why It Was Not Matched from ITB": (
                f"ITB text does not explicitly name a {BUCKET_TO_DOCTYPE_LABEL[bucket]} for {display_fam}; "
                f"only the functional/scope requirement is stated."
            ),
            "Evidence from MDL / Excel": (
                f"Present in Integrated MDL under System(L1)/Sub-System(L2) = '{display_fam}', "
                f"Document Type = '{doc_type}'; not present in Step 2 matched-document set for this family."
            ),
            "Risk of Hallucination": "Low (title copied verbatim from Integrated MDL master catalog)",
            "Review Status": "Expert Inference / Review Required",
        })
        no += 1

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
