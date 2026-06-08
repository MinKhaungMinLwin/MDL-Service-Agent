# Doosan MDL — Project Guide

## What this project does

Automates MDL (Master Document List) generation for CCPP EPC projects.
Given an ITB (client requirements PDF) and historical MDL references,
produces FA/FC submission dates for each technical document.

**Detailed docs:** `docs/architecture.md` (full pipeline + diagrams) and `docs/workflows.md` (CLI commands).

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

## Two API workflows

### 1. `/schedule/candidates`  —  ITB chunk → MDL document candidates
```
output_match_*.csv  →  parse Matched_Doc_1..N (score ≥ 0.75)  →  mdl_candidates_*.csv
```
Answers: "Which MDL documents are needed to fulfill the ITB requirements?"
Preserves `itb_sources` column for end-to-end traceability.
Optional `classify_with_llm=true` fills missing Equipment/Deliverable via the MDL classifier.

### 2. `/schedule/generate`  —  MDL document → FA/FC dates
```
mdl_candidates_*.csv
  →  validation_rule match (hybrid token+semantic) + activity search (BM25+semantic+RRF) + date compute
  →  generated_schedule_*.json/xlsx
```
Answers: "When should each MDL document be submitted?"
Semantic matching is **mandatory** (no flags): rules always use hybrid token+semantic,
activities always use BM25+semantic+RRF — both require Azure credentials.
Optional: `ntp_date` (shift template dates to real calendar), `rule_csv`.

> A third route `/schedule/map` (ITB chunk → activity via BM25+semantic+LLM) was
> **removed** in the `feat/mia-2` reorg; activity lookup now lives inside `/generate`.

**Full pipeline:**
```
[CLI]  uv run itb-match  →  output_match_*.csv
                                    │
                                    ▼
                         /schedule/candidates
                         (parse Matched_Doc_1..N + dedup, opt. LLM classify)
                                    │
                                    ▼
                         mdl_candidates_*.csv
                         (MDL doc list + itb_sources)
                                    │
                                    ▼
                         /schedule/generate
                         (rule match + activity search + NTP shift + dates)
                                    │
                                    ▼
                         generated_schedule_*.json
                         (FA/FC dates per MDL doc)
```

---

## Key data files

```
data/schedule_service/processed/ccpp_guide_schedule_260527_clean.json  ← 4039 activities (DEFAULT_SCHEDULE_PATH)
data/schedule_service/processed/validation_rule_clean.csv               ← FA/FI rules (DEFAULT_RULE_PATH)
data/schedule_service/raw/validation_rule.csv                           ← raw rules (pre-clean source)
output/current_test_env/matching/*/output_match_*.csv                   ← ITB matching output
output/current_test_env/*_MDL_classified.csv                            ← classified MDL data
output/schedule_service/{candidates,generate,cache}/                    ← API outputs + caches
```

---

## How to run

```bash
source .venv/bin/activate
PYTHONPATH=src uvicorn api.main:app --reload --port 8000

# Full pipeline: ITB matching → MDL candidates → FA/FC dates
curl -X POST "http://localhost:8000/schedule/candidates" \
  --get --data-urlencode "input_csv=output/current_test_env/matching/hybrid/output_match_all_projects_section6.csv"

curl -X POST "http://localhost:8000/schedule/generate" \
  --get \
  --data-urlencode "input_csv=output/schedule_service/candidates/mdl_candidates_output_match_all_projects_section6.csv" \
  --data-urlencode "ntp_date=2024-03-01"

# Or use historical MDL directly
curl -X POST "http://localhost:8000/schedule/generate" \
  --get --data-urlencode "input_csv=output/current_test_env/Fadhili_MDL_classified.csv" -d "limit=50"

# Optional flags: classify_with_llm (candidates); rule_csv (generate).
# Note: /schedule/generate always uses semantic matching → requires Azure credentials.

# Lint / test
ruff check src/
python -m pytest src/schedule_service/tests/ -v
```

---

## Known gaps

1. **NTP shift, not real PO dates** — `ntp_date` linearly shifts all template dates (anchored at `2007-03-01`); per-activity client PO dates are still not mapped. `ScheduleActivity.po_finish_date` always `""`.
2. **ITB + MDL classification are CLI-first** — exposed through `mdl-classify`, `mdl-ingest`, `itb-extract`, and `itb-match`.
3. **No LLM-validated activity selection** — the old `/schedule/map` route was removed; `/schedule/generate` picks the activity via BM25+semantic+RRF per MDL document.
4. **No final MDL Excel formatter** — output is an internal table, not the client deliverable.

_Resolved: the semantic index is now cached (`resource_cache` + disk caches), no longer re-embedded per request._

---

## Environment variables

```
AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY
AZURE_OPENAI_CHAT_DEPLOYMENT   (e.g. gpt-5.2)
EMBEDDING_MODEL                (text-embedding-3-large)
EMBEDDING_DIMENSIONS / EMBEDDING_BATCH_SIZE
NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE
```
