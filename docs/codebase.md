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
│       └── schedule.py              POST /schedule/candidates|generate
│
├── schedule_service/
│   ├── normalizer.py                Single source of truth: equipment + deliverable normalization
│   ├── output_writer.py             Write JSON + formatted XLSX
│   │
│   ├── candidate/                   /schedule/candidates
│   │   ├── candidate_extractor.py   Parse Matched_Doc_1..N → MDL candidate rows
│   │   └── llm_classify_cache.py    Disk cache: title → Equipment/Building/System/Deliverable
│   │
│   ├── generate/                    /schedule/generate
│   │   ├── schedule_generator.py    Orchestration: rule match → activity match → date compute
│   │   ├── _shared/
│   │   │   ├── cosine_index.py          CosineIndex base (numpy cosine, disk-cached by corpus hash)
│   │   │   ├── resource_cache.py        Process-level memoized activities / BM25 / matcher / semantic
│   │   │   └── embedding_cache.py       In-process query-text → embedding cache
│   │   ├── activity/                Activity matching (BM25 + semantic + RRF, mandatory)
│   │   │   ├── loader.py                Load guide schedule JSON → list[ScheduleActivity]
│   │   │   ├── lexical.py               BM25Index (keyword scoring)
│   │   │   ├── semantic.py              SemanticIndex (extends CosineIndex)
│   │   │   ├── matcher.py               build_activity_query, resolve_activities, rrf_candidates, anchor
│   │   │   └── models.py                ScheduleActivity, Candidate dataclasses
│   │   ├── rule/                    Rule matching (hybrid token + semantic, mandatory)
│   │   │   ├── loader.py                load_rules + DEFAULT_RULE_PATH (Pur. → sub_type)
│   │   │   ├── lexical.py               RuleLexicalIndex (inverted token index + token_score)
│   │   │   ├── matcher.py               RuleMatcher.match_with_embedding, build_rule_query, resolve_rules
│   │   │   ├── semantic.py              RuleSemanticIndex (embedded doc_keyword + item_name)
│   │   │   ├── models.py                ValidationRule, tokenize
│   │   │   └── vt_parser.py             Parse "start+4W<=FA<=start+6W" → day offsets
│   │   └── date/
│   │       └── date_range_engine.py     Compute FA/FC DateRange from anchor + VT formula
│   │
│   ├── data_prep/                   Offline CLI cleaners (run once)
│   │   ├── ccpp_schedule_cleaner.py     Clean raw CCPP guide schedule XLSX → JSON
│   │   └── validation_rule_cleaner.py   Clean validation_rule.csv (encoding/whitespace)
│   │
│   └── tests/                       pytest suite (test_rule_loader, test_vt_parser,
│                                    test_normalizer, test_date_range_engine,
│                                    test_candidate_extractor, test_schedule_generator_flow,
│                                    test_schedule_generator_helpers)
│
├── common/
│   ├── config.py                    load_env_file, required_env, azure_endpoint
│   ├── embedding_client.py          AzureEmbeddingService — batch embed
│   ├── neo4j_client.py              Neo4j driver wrapper
│   ├── openai_client.py             Build AzureOpenAI client from env
│   ├── text_normalizer.py           build_schedule_target_text, expand_abbreviations
│   ├── json_io.py / llm_json.py / prompts.py
│   └── normalization_rules/
│       └── abbreviations.json       HRSG→"Heat Recovery Steam Generator", etc.
│
├── parser_service/                  Docling PDF parser
├── chunker_service/                 Docling chunker
├── mdl_service/                     MDL classification + ingestion CLI
├── itb_service/                     ITB extraction CLI
├── matching_service/                ITB→MDL Neo4j matching CLI
└── evaluation_service/              Ground-truth build + matching evaluation CLI
```
---

## Key data files (outside src/)

```
data/schedule_service/
  processed/
    ccpp_guide_schedule_260527_clean.json   4039 CCPP schedule activities  (DEFAULT_SCHEDULE_PATH)
    validation_rule_clean.csv               validation rules               (DEFAULT_RULE_PATH)
  raw/
    ccpp guide schedule_260527.xlsx         source workbook for the cleaner
    validation_rule.csv                     raw rules (pre-clean)
    mock_validation_rule.csv                small fixture for testing
    activity_base_date_policy.csv           base-date policy per activity type

output/current_test_env/
  itb_extract/                              ITB keyword extraction CSVs
  matching/{keyword,semantic,hybrid}/       output_match_*.csv  (ITB→MDL Neo4j matches)
  *_MDL_classified.csv                      classified historical MDL (one per project)

output/schedule_service/                    API outputs
  candidates/   mdl_candidates_*.csv        /schedule/candidates output
  generate/     generated_schedule_*.json/xlsx   /schedule/generate output
  cache/        rule_semantic_cache/, activity_semantic_cache/, llm_classify_cache.json
```

---

## Module details

### `candidate/candidate_extractor.py`

**Purpose:** Bridge between ITB matching output and the MDL schedule pipeline.

**Input columns read from ITB matching CSV:**
- `Document` — ITB source file name (e.g. "R&N_ITB")
- `Page` — page number
- `Matched_Doc_1` … `Matched_Doc_N` — Neo4j results

**Matched_Doc naming formats:**
```
[Project] EQUIPMENT - TITLE (Semantic: 0.91 / CrossEncoder: ...)
[Project] DOC_NO - [Equipment bracket] TITLE (...)
[Project] EQUIP_TITLE_WITHOUT_SEPARATOR (...)
```

**Score extraction (`_extract_score`)** — handles format evolution:
- New hybrid/semantic format → use `Semantic:` (0–1 cosine, comparable to threshold).
- Old Korean pipeline → use `최종점수:` / `Vector:` (can exceed 1).
- `CrossEncoder:` only as last resort and only if positive (ms-marco logit scale).

**Key constants:**
- `DEFAULT_SCORE_THRESHOLD = 0.75` (new format). Old `최종점수` format → use 0.85.
- `DEFAULT_TOP_N = 5` — consider only Matched_Doc_1..5 per row.

**Optional `classify_with_llm=True`:** re-classifies Equipment/Building/System/Deliverable
via the MDL LLM classifier — but only for candidates where regex left a field blank.
Results are disk-cached by title (`llm_classify_cache.py`), batched, and run in parallel
(`ThreadPoolExecutor`).

**Output columns** (compatible with `*_MDL_classified.csv` + 2 extra):
- `match_score` — highest score across all ITB chunks that matched this doc
- `itb_sources` — "R&N_ITB:p97(score=0.93) | R&N_ITB:p98(score=0.91)"

---

### `generate/schedule_generator.py`

**Purpose:** FA/FC date range computation for each MDL document.

**Pipeline is a 3-pass design** (matching is done up-front, not per-row):
1. `resolve_rules` — one validation rule per row (hybrid token+embedding, mandatory).
2. `resolve_activities` — one CCPP activity per row (BM25+semantic+RRF, mandatory).
3. `_format_schedule_row` — render output only; never re-runs matching.

**`generate_schedule_file` parameters:**
- `ntp_date` — real project NTP (ISO). Shifts all template dates by
  `(ntp_date − TEMPLATE_NTP)` where `TEMPLATE_NTP = 2007-03-01`.
- `semantic_cache_dir` — disk cache for rule embeddings (hybrid match is always on).
- `semantic_weight` — weight of semantic score in hybrid rule scoring (default 0.3).
- `activity_cache_dir` — disk cache for activity embeddings (BM25+semantic+RRF is always on).
- `rule_path`, `limit`.

> Semantic matching is mandatory — there are no `use_semantic_*` flags. Both
> `semantic_cache_dir` and `activity_cache_dir` are supplied by the API/CLI; omitting
> them while a rule file is present raises a clear error (requires Azure credentials).

**Query construction (single source of truth):**
- `build_rule_query` (in `rule/matcher.py`) → `normalize_deliverable(Deliverable) + " for " + equipment_to_abbr(scope)`
  where `scope = Equipment or System or Building`.
- `build_activity_query` (in `activity/matcher.py`) → `Equipment + System + norm_deliverable + Title`, plus a
  **phase boost**: `_DELIVERABLE_PHASE_BOOST` (takes priority) or the rule's
  `_ACTIVITY_KW_BOOST` — steers BM25 toward the right project phase.

**Anchor selection (`resolve_anchor_date` in `activity/matcher.py`):** finish_date when the rule's
`activity_keywords` hit `_FINISH_DATE_KEYWORDS` ({transportation, delivery, fob,
manufacturing, fo b}); else start_date. Falls back to the other date if the preferred
one is empty, then applies the NTP shift.

**Output stem:** `generated_schedule_{input_csv.stem}` (+ `_ntp{date}`, `_limit{n}`).

---

### `generate/_shared/resource_cache.py`

**Purpose:** Process-level memoization so a long-running server pays each build cost once
(~13 s otherwise per request). Keyed by `(path, mtime)` for files, or list/table identity
for derived indexes; a `Lock` guards population only. Cached objects are read-only after
construction, so they are safe to share across concurrent requests.

Exposes: `get_schedule_activities`, `get_bm25_index`, `get_rule_matcher`,
`get_activity_semantic_index`, `get_rule_semantic_index`, `clear`.

> This fixes the old "semantic cache disabled / re-embeds every call" gap.

### `generate/_shared/embedding_cache.py`

In-process `text → embedding` cache (`embed_texts_cached`) so repeated runs of the same
input CSV only embed previously unseen query strings.

---

### `generate/rule/loader.py` + `generate/rule/matcher.py`

**Purpose:** Load and match MDL validation rules.

**CSV format** (semicolon-delimited, UTF-8-BOM):
```
Priority;Item;MDL Document Keyword;Activity Keyword;Pur.;Validation Time
1;Gas Turbine Generator;P&ID for Gas Turbine Generator;GTG|P.O;FA;start+3M<=FA<=start+5M
```

**`Pur.` → `sub_type`** via `_SUB_TYPE_MAP` (fa/ap/fa-fi→FA, fi/if/ifi/ifr→FI,
as built/unmatch→SKIP). **Empty `Pur.`** is *inferred from the VT formula* (FA if the
formula has an FA/FC rule, else SKIP) — 2896 rules rely on this.

**Hybrid match (`match_with_embedding`)** — the only matching entry point (no token-only
`match`). It fuses a length-normalized token (Jaccard) recall with a cosine similarity:
```python
token  = |kw_tokens ∩ doc_tokens| / max(|kw_tokens|, 3)
hybrid = token·(1 − w) + semantic·w        # w = semantic_weight (default 0.3)
final  = hybrid · priority_weight[priority] # 1.0 / 0.85 / 0.70 ; threshold 0.2
```
The `max(…, 3)` penalizes 1–2-token generic rules ("GENERATOR", "P&ID") that would
otherwise score 1.0 and beat specific rules. A minimum token overlap is required (no
pure-semantic false positives). Ties break by item-name context fit, then priority. Uses
an inverted token index (5918 → ~30–100 candidates) before scoring.

> Rule selection runs per row inside `resolve_rules` (`rule/matcher.py`); the semantic
> similarities come pre-computed in one bulk matmul (see `rule/semantic.py`).

### `generate/rule/semantic.py`

`RuleSemanticIndex` — embeds each rule's `doc_keyword + item_name` at build time, cached on
disk (`validation_rule_embeddings.json`) keyed by a SHA-256 of all rule texts so it
invalidates when the CSV changes. `score_matrix` does a bulk numpy matmul for all queries.

### `generate/rule/vt_parser.py`

Parse Validation Time formulas. Units `D`=1, `W`=7, `M`=30, `Y`=365.
```
start+4W<=FA<=start+6W       → fa_lo=28d, fa_hi=42d
start+8W<=FA<=FC<=start+20W  → fa and fc both [56d, 140d]
start+3M<=FC<=start+5M       → fc_lo=90d, fc_hi=150d
start<=FA<=start+2M          → fa_lo=0d, fa_hi=60d
```

---

### `generate/date/date_range_engine.py`

```python
fa_earliest    = anchor + fa_lo_days
fa_latest      = anchor + fa_hi_days
fa_recommended = midpoint(fa_earliest, fa_latest)

# FC: use formula if present, else default fa_recommended + 60d ± 15d
# Enforces a minimum FA→FC gap of 21 days (guards chained VT formulas)
# ntp_floor: clamps any date earlier than the shifted NTP up to the NTP
confidence = {1: 0.9, 2: 0.6, 3: 0.3}.get(priority, 0.2)
```

---

### `normalizer.py`

Central pre-processing layer (single source of truth) used by candidate_extractor,
schedule_generator, and rule_loader:
- `normalize_equipment` / `extract_equipment_from_title` — raw → canonical equipment.
- `equipment_to_abbr` — canonical → abbreviation used in validation_rule.csv (HRSG, GTG…).
- `normalize_deliverable` / `extract_deliverable` — raw deliverable → rule-keyword form.
- `expand_query_tokens` — inject equipment abbreviations when all full-name tokens present.

Changing a mapping here propagates to every consumer automatically.

---
