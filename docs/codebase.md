# Codebase Reference

## Directory structure

```
src/
├── api/
│   ├── main.py                      FastAPI app factory, mounts all routers
│   └── routes/
│       ├── health.py                GET /health
│       ├── parser.py                POST /parser  — PDF → parsed JSON (Docling)
│       ├── chunker.py               POST /chunker — PDF → chunks JSON (Docling)
│       └── schedule.py              POST /schedule/map|candidates|generate
│
├── schedule_service/
│   ├── candidate_extractor.py       /schedule/candidates logic
│   ├── schedule_generator.py        /schedule/generate logic
│   ├── activity_mapper.py           /schedule/map logic
│   ├── llm_validator.py             Azure OpenAI: pick best activity from candidates
│   ├── schedule_loader.py           Load guide schedule JSON → List[ScheduleActivity]
│   ├── schedule_cleaner.py          CLI: clean raw CCPP guide schedule XLSX → JSON
│   ├── rule_loader.py               Load validation_rule.csv → RuleTable
│   ├── vt_parser.py                 Parse "start+4W<=FA<=start+6W" → day offsets
│   ├── date_range_engine.py         Compute FA/FC DateRange from anchor + VT formula
│   ├── models.py                    ScheduleActivity, Candidate dataclasses
│   ├── output_writer.py             Write JSON + formatted XLSX
│   ├── search/
│   │   ├── keyword_search.py        BM25Index
│   │   ├── semantic_search.py       Azure OpenAI cosine-similarity index
│   │   └── reranker.py              Reciprocal Rank Fusion (RRF)
│   └── docs/                        ← you are here
│       ├── architecture.md
│       └── codebase.md
│
├── common/
│   ├── config.py                    load_env_file, required_env, azure_endpoint
│   ├── embedding_client.py          AzureEmbeddingService — batch embed
│   ├── neo4j_client.py              Neo4j driver wrapper
│   ├── openai_client.py             Build AzureOpenAI client from env
│   ├── text_normalizer.py           build_schedule_target_text, expand_abbreviations
│   └── normalization_rules/
│       └── abbreviations.json       HRSG→"Heat Recovery Steam Generator", etc.
│
├── parser_service/
│   ├── docling_parser.py
│   └── service.py
│
├── chunker_service/
│   ├── docling_chunker.py
│   ├── docling_loader.py
│   └── service.py
│
└── AGENTS.md                        Quick-start guide for AI agents
```

---

## Key data files (outside src/)

```
data/schedule_sources/
  processed/
    ccpp_guide_schedule_260527_clean.json   4039 CCPP schedule activities
  rules/
    validation_rule.csv                     5918 FA/FI/SKIP rules (semicolon-delimited)
    activity_base_date_policy.csv           Base date policy per activity type

output/current_test_env/
  itb_extract/
    itb_extraction_section6.csv             ITB keyword extraction (Section 6)
    itb_extraction_section7.csv             ITB keyword extraction (Section 7)
  matching/
    keyword|semantic|hybrid/
      output_match_all_projects_section6.csv ITB to MDL Neo4j matches (Section 6)
      output_match_all_projects_section7.csv ITB to MDL Neo4j matches (Section 7)
  Fadhili_MDL_classified.csv                Classified MDL (2682 rows)
  Grati_MDL_classified.csv
  ... (one per historical project)

output/schedule_service/                    API outputs
  mdl_candidates_*.csv                      /schedule/candidates output
  generated_schedule_*.json/xlsx            /schedule/generate output
  schedule_mapping_*.json/xlsx              /schedule/map output
```

---

## Module details

### `candidate_extractor.py`

**Purpose:** Bridge between ITB matching output and MDL schedule pipeline.

**Input columns read from ITB matching CSV:**
- `Document` — ITB source file name (e.g. "R&N_ITB")
- `Page` — page number
- `Search Query` — LLM-generated search query
- `Matched_Doc_1` … `Matched_Doc_20` — Neo4j results

**Matched_Doc naming formats:**
```
[Project] EQUIPMENT - TITLE (최종점수: X.XX / 기본: Y.YY)
[Project] [Equipment bracket] EQUIP_CODE_TITLE (최종점수: X.XX)
[Project] TITLE WITHOUT SEPARATOR (최종점수: X.XX)
```

**Key constants:**
- `DEFAULT_SCORE_THRESHOLD = 0.85` — filter out weak matches
- `DEFAULT_TOP_N = 5` — consider only Matched_Doc_1..5 per row
- `_DELIVERABLE_KEYWORDS` — ordered list used to extract deliverable from title
- `_EQUIPMENT_NORM` — abbreviation map: GTG→"Gas Turbine Generator", etc.

**Output columns:**
Compatible with `*_MDL_classified.csv` + 2 extra:
- `match_score` — highest score across all ITB chunks that matched this doc
- `itb_sources` — "R&N_ITB:p97(score=0.93) | R&N_ITB:p98(score=0.91)"

---

### `schedule_generator.py`

**Purpose:** FA/FC date range computation for each MDL document.

**Input columns read:**
- `Title`, `Deliverable`, `Equipment`, `System`, `Building`, `Document No`, `Source File`
- `itb_sources` — passed through to output (traceability)

**Key constants:**
- `_DELIVERABLE_NORM` — maps MDL deliverable terms to validation_rule keywords:
  `"P&I DIAGRAM"` → `"P&ID"`, `"GENERAL ARRANGEMENT"` → `"General Arrangement Drawing"`, etc.
- `_FINISH_DATE_KEYWORDS` — `{"transportation", "delivery", "fob", "manufacturing"}`
  If rule's activity_keywords overlap → use `activity.finish_date` as anchor instead of `start_date`

**Processing per row:**
```python
norm_del   = _DELIVERABLE_NORM.get(deliverable.upper(), deliverable)
scope      = equipment or system or building
rule_query = f"{norm_del} for {scope}"      # e.g. "P&ID for Gas Turbine Generator"

rule = rule_table.match(rule_query) or rule_table.match(title)
# rule → sub_type ("FA"/"FI"/"SKIP"), vt_parsed, priority

scores = bm25.score(f"{equipment} {system} {norm_del} {title}")
activity = activities[argmax(scores)]

anchor = activity.start_date  # or finish_date
dr = compute_date_range(rule.vt_parsed, anchor, sub_type, rule.priority)
```

**Output stem:** `generated_schedule_{input_csv.stem}`

---

### `activity_mapper.py`

**Purpose:** Map ITB chunks to CCPP guide schedule activities using BM25 + semantic + LLM.

**Key parameters:**
- `retrieve_k=50` — candidates retrieved from each search method before RRF
- `top_k=10` — candidates passed to LLM after reranking
- `use_semantic=True` — if False, uses BM25 only (no Azure API cost)
- `use_llm=True` — if False, skips LLM selection step

**Query construction:**
```python
query = row.get("Search Query", "").strip()
# fallback if empty:
query = " ".join([row.get("Search_Queries",""), row.get("Keywords",""), row.get("Depth_Context","")])
```

⚠️ `SemanticIndex.build()` has `del cache_dir` — re-embeds all 4039 activities on every call.

---

### `rule_loader.py`

**Purpose:** Load and match validation rules.

**CSV format** (semicolon-delimited, UTF-8-BOM):
```
Priority;Abb.;Item;MDL Document Keyword;Activity Keyword;Pur.;Date_choice;Validation Time
1;GTG;Gas Turbine Generator;P&ID for Gas Turbine Generator;GTG|P.O;FA;Max;start+3M<=FA<=start+5M
```

**`Pur.` → `sub_type` mapping:**
```
"fa" / "ap" / "fa/fi"  → "FA"
"fi" / "if" / "ifi" / "ifr" → "FI"
"as built" / "unmatch" → "SKIP"
```

**Match algorithm:**
```python
score = |kw_tokens ∩ doc_tokens| / |kw_tokens|   # Jaccard over tokens
# threshold = 0.5, returns best score + lowest priority
```

⚠️ Threshold 0.5 causes false positives for generic tokens ("system", "drawing", "calculation").

**Performance:** Uses inverted token index to narrow 5918 rules → ~30-100 candidates before scoring.

---

### `vt_parser.py`

**Purpose:** Parse Validation Time formula strings.

**Supported patterns:**
```
start+4W<=FA<=start+6W          → fa_lo=28d, fa_hi=42d
start+8W<=FA<=FC<=start+20W     → fa and fc both [56d, 140d]
start+3M<=FC<=start+5M          → fc_lo=90d, fc_hi=150d
start<=FA<=start+2M             → fa_lo=0d, fa_hi=60d
```

Units: `D`=1, `W`=7, `M`=30, `Y`=365 days.

⚠️ `anchor` field is parsed ("start"/"finish") but ignored by `schedule_generator` — uses keyword heuristic instead.

---

### `date_range_engine.py`

**Purpose:** Compute FA/FC date ranges.

```python
fa_earliest    = anchor + timedelta(days=fa_lo_days)
fa_latest      = anchor + timedelta(days=fa_hi_days)
fa_recommended = fa_earliest + (fa_latest - fa_earliest) / 2

# FC: use formula if available, else default
fc_center   = fa_recommended + timedelta(days=60)
fc_earliest = fc_center - timedelta(days=15)
fc_latest   = fc_center + timedelta(days=15)

confidence = {1: 0.9, 2: 0.6, 3: 0.3}.get(priority, 0.2)
```

---

### `models.py`

```python
@dataclass(frozen=True)
class ScheduleActivity:
    activity_id: str
    activity_name: str
    activity_name_clean: str     # activity_name with NTP suffixes removed
    wbs_path: str                # "CCPP > Mechanical > GTG"
    start_date: str              # ISO date, used as FA/FC anchor
    finish_date: str
    target_text: str             # normalized text for BM25/semantic
    # Always "" — awaiting client PO mapping:
    po_start_date: str = ""
    po_finish_date: str = ""
    ntp_date: str = ""
    icod_date: str = ""
    pcod_date: str = ""

@dataclass(frozen=True)
class Candidate:
    activity: ScheduleActivity
    bm25_rank: int | None
    semantic_rank: int | None
    bm25_score: float
    semantic_score: float
    rrf_score: float
```

---

## How to add a new route

1. Add logic to a new or existing `schedule_service/*.py` file
2. Import in `api/routes/schedule.py`
3. Add `@router.post("/your-route", ...)` handler
4. Handler should call `_existing_path()` for any path parameter
5. Handler should call `_file_response()` if output is JSON+XLSX files

## How to run locally

```bash
cd /path/to/doosan-mdl
source .venv/bin/activate
PYTHONPATH=src uvicorn api.main:app --reload --port 8000

# Quick test (no Azure API calls)
PYTHONPATH=src python3 -c "
from schedule_service.schedule_generator import generate_schedule_file
from schedule_service.schedule_loader import load_schedule_activities, DEFAULT_SCHEDULE_PATH
from pathlib import Path
acts = load_schedule_activities(DEFAULT_SCHEDULE_PATH)
generate_schedule_file(
    Path('output/current_test_env/Fadhili_MDL_classified.csv'),
    acts, Path('output/schedule_service'), limit=10
)
"

# Lint
ruff check src/
```
