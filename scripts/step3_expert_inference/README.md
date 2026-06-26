# Step 3 — Expert Inferred Documents pipeline

Generates `Expert_Inferred_Documents` (the third sheet of
`R&N_ITB_EBS_MDL_Match_Final.xlsx`, also exported as
`Step 3_Expert_Inferred_Documents.csv`): MDL documents not directly matched
from ITB text in Step 2, but identified as engineering-necessary for the
Equipment/Building/System families extracted in Step 1.

## Run order

```bash
source .venv/bin/activate   # repo venv, needs pandas + openpyxl

python scripts/step3_expert_inference/01_convert_mdl_to_csv.py
python scripts/step3_expert_inference/02_gap_analysis.py
python scripts/step3_expert_inference/03_curate_gaps.py
python scripts/step3_expert_inference/04_select_and_rationale.py
python scripts/step3_expert_inference/05_build_workbook.py
```

## Inputs

| File | Location | Notes |
| --- | --- | --- |
| `vendor_package_integrated_mdl_all.xlsx` | repo root | Master MDL catalog, sheet `Integrated MDL` (~7,938 rows). **Not currently committed to git** — see "Known gap" below. |
| `R&N_ITB_EBS_MDL_Match_Final_ITB_EBS_List.csv` | repo root | Step 1 output (ITB → Equipment/Building/System extraction). Tracked in git. |
| `R&N_ITB_EBS_MDL_Match_Final_Matched_Document_List.csv` | repo root | Step 2 output (ITB-text-matched MDL documents). Tracked in git. |

## What each script does

1. **`01_convert_mdl_to_csv.py`** — converts the `Integrated MDL` sheet of the
   xlsx to `integrated_mdl.csv` (read as strings to avoid pandas mangling
   numeric-looking text or coercing dates).
2. **`02_gap_analysis.py`** — joins Step 1 families against the MDL catalog,
   subtracts anything already matched in Step 2, buckets remaining
   candidates by document-type class (Spec/DataSheet, Drawing/GA,
   Calculation, Manual/O&M, List/Schedule, Test/Commissioning, Other).
   Writes `family_gap_analysis.csv` and `family_summary.csv` (human-readable
   intermediate artifacts).
3. **`03_curate_gaps.py`** — fixes a quirk in step 2: a handful of Building
   rows in Step 1 use a comma-joined alias list as the family name (e.g.
   `"CCB, CENTRAL CONTROL BUILDING, Control Center, ..."`), which never
   matches a single MDL value. This script splits those aliases and
   recomputes gaps per individual alias, then drops the `OTHER` bucket and
   two mega-generic "junk-drawer" families (`General`, `Plant General
   System`) that are too broad to safely infer specific documents from.
   Writes `curated_gap_records.json`.
4. **`04_select_and_rationale.py`** — for each (family, gap-bucket) record,
   picks the single most relevant candidate title (prefers titles containing
   a token from the family name, then the shortest/most generic title), and
   generates an engineering rationale from a per-bucket template. Writes
   `expert_inferred_documents.csv` (243 rows as of the last run).
5. **`05_build_workbook.py`** — assembles the final 3-sheet workbook
   (`ITB_EBS_List`, `Matched_Document_List`, `Expert_Inferred_Documents`)
   with header styling, frozen header row, autofilter, and amber
   highlighting on review-required rows. Writes
   `R&N_ITB_EBS_MDL_Match_Final.xlsx` to the repo root.

## Guarantees enforced by this pipeline

- **No fabricated titles**: every `Recommended Document Title` in the output
  is copied verbatim from the Integrated MDL master catalog.
- **No duplicate matches**: titles already present in Step 2's matched-
  document set (for the same family) are excluded from Step 3 candidates.

## Known gap

`vendor_package_integrated_mdl_all.xlsx` is **not committed to this repo** —
it was supplied as a local file outside the repo during development and is
required to re-run script 01 from scratch. If you need to regenerate the
pipeline end-to-end on a fresh checkout, source this file separately (it's
the master vendor-package MDL catalog) and place it at the repo root before
running script 01. Scripts 02–05 only need `integrated_mdl.csv` (the output
of script 01), so if that file already exists in this directory you can skip
script 01 and start from script 02.
