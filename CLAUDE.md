# Doosan MDL — Project Guide

## What this project does

Automates MDL (Master Document List) generation for CCPP EPC projects.
Given an ITB (client requirements PDF) and historical MDL references,
produces FA/FC submission dates for each technical document.

**Detailed docs:** `docs/architecture.md` (full pipeline + diagrams), `docs/codebase.md` (file map + module details), and `docs/workflows.md` (CLI commands).

---

## Domain concepts (essential)

| Term | Meaning |
|------|---------|
| **ITB** | Invitation To Bid — client PDF describing project requirements |
| **MDL** | Master Document List — documents EPC contractor must deliver |
| **CCPP** | Combined Cycle Power Plant (Gas Turbine + HRSG + Steam Turbine) |
| **FA** | First Approval — first submission date |
| **FC** | Final Comment — final submission after review |
| **FI** | For Information — no approval needed |
| **CCPP Guide Schedule** | Doosan standard reference schedule (4039 activities) |
| **Validation Rule** | Maps MDL document type → FA/FI/SKIP + VT formula |
| **VT Formula** | Date offset formula: `start+4W<=FA<=start+6W` |

---

## Three API workflows

### 1. `/schedule/map`  —  ITB chunk → CCPP schedule activity
```
output_match_*.csv  →  BM25 + Azure OpenAI semantic + RRF + LLM  →  schedule_mapping_*.json
```
Answers: "Which CCPP guide schedule activity does each ITB requirement correspond to?"

### 2. `/schedule/candidates`  —  ITB chunk → MDL document candidates
```
output_match_*.csv  →  parse Matched_Doc_1..N (score ≥ 0.85)  →  mdl_candidates_*.csv
```
Answers: "Which MDL documents are needed to fulfill the ITB requirements?"
Preserves `itb_sources` column for end-to-end traceability.

### 3. `/schedule/generate`  —  MDL document → FA/FC dates
```
mdl_candidates_*.csv
  →  validation_rule match + BM25 activity search + date compute
  →  generated_schedule_*.json/xlsx
```
Answers: "When should each MDL document be submitted?"

**Full connected pipeline:**
```
[CLI]  uv run itb-match  →  output_match_*.csv
                                                    │
                          ┌─────────────────────────┤
                          │                         │
                          ▼                         ▼
               /schedule/map              /schedule/candidates
               (BM25+semantic+LLM)        (parse Matched_Doc_1..N)
                          │                         │
                          ▼                         ▼
             schedule_mapping_*.json      mdl_candidates_*.csv
             (activity per ITB chunk)     (MDL doc list + itb_sources)
             ⚠️ not yet used downstream             │
                                                    ▼
                                         /schedule/generate
                                         (rule match + BM25 + dates)
                                                    │
                                                    ▼
                                         generated_schedule_*.json
                                         (FA/FC dates per MDL doc)
```

---

## Key data files

```
data/schedule_sources/processed/ccpp_guide_schedule_260527_clean.json  ← 4039 activities
data/schedule_sources/rules/validation_rule.csv                         ← 5918 FA/FI rules
output/current_test_env/output_match_*.csv                                  ← ITB matching output
output/current_test_env/*_MDL_classified.csv                                ← classified MDL data
output/schedule_service/                                                    ← API outputs
```

---

## How to run

```bash
source .venv/bin/activate
PYTHONPATH=src uvicorn api.main:app --reload --port 8000

# Full pipeline: ITB matching → MDL candidates → FA/FC dates
curl -X POST "http://localhost:8000/schedule/candidates" \
  --get --data-urlencode "input_csv=output/current_test_env/output_match_all_projects_section6.csv"

curl -X POST "http://localhost:8000/schedule/generate" \
  --get --data-urlencode "input_csv=output/schedule_service/mdl_candidates_output_match_all_projects_section6.csv"

# Or use historical MDL directly
curl -X POST "http://localhost:8000/schedule/generate" \
  --get --data-urlencode "input_csv=output/current_test_env/Fadhili_MDL_classified.csv" -d "limit=50"

# Lint / test
ruff check src/
python -m pytest src/ -v
```

---

## Known gaps

1. **Anchor dates are 2007–2009** — guide schedule template dates, not real PO dates. `ScheduleActivity.po_finish_date` always `""`.
2. **ITB + MDL classification are CLI-first** — exposed through `mdl-classify`, `mdl-ingest`, `itb-extract`, and `itb-match`.
3. **`/schedule/map` output not connected to `/schedule/generate`** — activity lookup happens independently via BM25.
4. **Semantic cache disabled** — `del cache_dir` in `SemanticIndex.build()` re-embeds 4039 activities every `/schedule/map` call.
5. **No final MDL Excel formatter** — output is an internal table, not the client deliverable.

---

## Environment variables

```
AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY
AZURE_OPENAI_CHAT_DEPLOYMENT   (e.g. gpt-5.2)
EMBEDDING_MODEL                (text-embedding-3-large)
EMBEDDING_DIMENSIONS / EMBEDDING_BATCH_SIZE
NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE
```
