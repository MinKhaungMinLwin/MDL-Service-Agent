# Rule Matching — CCPP / MDL Candidate / Validation Rule

## 3 Components and Roles

| Component | Answers | Unknown |
|-----------|---------|---------|
| **Validation Rule** | Is this doc submitted as FA or FI? What is the submission timeframe? | Specific date |
| **CCPP Guide Schedule** | When does this activity start in the CCPP timeline? | Document type |
| **MDL Candidate** | Bridges both sides — has Deliverable + Equipment for querying both | — |

---

## Interaction diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  MDL CANDIDATE (1 row)                                              │
│  Title="P&I DIAGRAM FOR GT ROTOR COOLING AIR COOLER"                │
│  Deliverable="P&I DIAGRAM"                                          │
│  Equipment="Gas Turbine Generator"                                  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
          ┌────────────────┴────────────────┐
          │                                 │
          ▼                                 ▼
┌─────────────────────┐         ┌────────────────────────┐
│  VALIDATION RULE    │         │  CCPP GUIDE SCHEDULE   │
│  validation_rule.csv│         │  4039 activities       │
│                     │         │                        │
│  Match by:          │         │  Match by:             │
│  normalize(Deliv.)  │         │  BM25(Equipment +      │
│  + " for " + Equip  │         │    System + Deliv.     │
│                     │         │    + Title)            │
│  Returns:           │         │                        │
│  sub_type = "FA"    │         │  Returns:              │
│  vt_parsed = {      │         │  activity.start_date   │
│    fa_lo_days: 84,  │         │  = "2007-05-01"        │
│    fa_hi_days: 126  │         │  → + NTP shift         │
│  }                  │         │  = "2024-04-17" (real) │
│  priority = 1       │         │                        │
└──────────┬──────────┘         └──────────┬─────────────┘
           │                               │
           └───────────────┬───────────────┘
                           ▼
              ┌────────────────────────┐
              │  DATE RANGE ENGINE     │
              │  compute_date_range()  │
              │                        │
              │  anchor = 2024-04-17   │
              │  + fa_lo_days = +84d   │
              │  + fa_hi_days = +126d  │
              │                        │
              │  fa_earliest  = 07-10  │
              │  fa_recommended= 07-31 │
              │  fa_latest    = 08-21  │
              │  fc = fa_rec + 60d     │
              │  confidence   = 0.90   │
              └────────────────────────┘
```

---

## Validation Rule — Structure and How to Read

File: `data/schedule_service/processed/validation_rule_clean.csv` (semicolon-delimited)

```
Priority ; Item                  ; MDL Document Keyword              ; Activity Keyword ; Pur. ; Validation Time
1        ; Gas Turbine Generator ; P&ID for Gas Turbine Generator    ; GTG|P.O          ; FA   ; start+3M<=FA<=start+5M
```

| Field | Meaning | Used For |
|-------|---------|----------|
| `MDL Document Keyword` | Phrase match with `normalize(Deliverable) + " for " + Equipment` | Match rule |
| `Activity Keyword` | Hint for activity type (P.O, Foundation, Installation...) | Choose finish/start_date as anchor |
| `Pur.` | FA / FI / as built / unmatch | sub_type |
| `Validation Time` | `start+3M<=FA<=start+5M` | VT formula → day offsets |
| `Priority` | 1=specific, 3=generic | Confidence (0.9/0.6/0.3) |

**`Pur.` → `sub_type` mapping:**
```
fa / ap / fa/fi      → "FA"
fi / if / ifi / ifr  → "FI"
as built / unmatch   → "SKIP"  ← document does not need scheduling
empty Pur.           → inferred from VT formula: FA if it has an FA/FC rule,
                        else SKIP  (2896 rules rely on this)
other value          → "SKIP"
```

**Hybrid match (mandatory — `match_with_embedding`):** the only rule-matching path.
There is no token-only fallback. It fuses a length-normalized token recall with a cosine
similarity from `RuleSemanticIndex` (embedded `doc_keyword + item_name`):
```python
token_score = |kw_tokens ∩ doc_tokens| / max(|kw_tokens|, 3)
hybrid = token_score·(1 − w) + semantic·w          # w = semantic_weight, default 0.3
final  = hybrid · priority_weight[priority]         # 1.0 / 0.85 / 0.70 ; threshold 0.2
# max(…, 3) penalizes 1–2-token generic rules ("GENERATOR", "P&ID")
# requires minimum token overlap (no pure-semantic false positives)
# ties: prefer rule whose item_name tokens appear in the query, then lowest priority
# inverted token index narrows 5918 rules → ~30–100 candidates before scoring
```

---

## CCPP Guide Schedule — Structure and Anchor Date

File: `data/schedule_service/processed/ccpp_guide_schedule_260527_clean.json` (4039 activities)

```json
{
  "activity_id"  : "1EF3020W00A15",
  "activity_name": "P.O & Procurement for GT",
  "wbs_path"     : "CCPP > Mechanical > GTG",
  "start_date"   : "2007-05-01",   ← template date, anchored at NTP=2007-03-01
  "finish_date"  : "2007-08-31",
  "target_text"  : "P.O Procurement GT 1EF3020W00A15 ..."
}
```

**Template NTP = 2007-03-01** — all dates in the schedule are relative offsets from this date.

**NTP shift:** when client provides real NTP date:
```
shift_days = (real_NTP - 2007-03-01).days
real_anchor = template_date + timedelta(days=shift_days)

Example: real_NTP = 2024-03-01
  shift = +6210 days
  "2007-05-01" → "2024-04-17"
```

**Anchor date selection** (`resolve_anchor_date`, keyword heuristic in `activity/matcher.py`):
```
rule.activity_keywords ∩ {transportation, delivery, fob, manufacturing, fo b}
  → use activity.finish_date
otherwise
  → use activity.start_date
(falls back to the other date when the preferred one is empty, then applies NTP shift)
```

---

## MDL Candidate — Bridge Between Two Sides

```
Validation rule needs:      MDL candidate provides:
  document type      →    Deliverable → normalize → "P&ID"
  equipment scope    →    Equipment = "Gas Turbine Generator"
  rule_query         →    "P&ID for Gas Turbine Generator"

CCPP schedule needs:        MDL candidate provides:
  search query       →    Equipment + System + Deliverable + Title
                          → BM25 + semantic + RRF → top-1 activity

Date engine needs:          source:
  sub_type           ←    Validation rule
  vt_parsed          ←    Validation rule (parsed VT formula)
  anchor_date        ←    CCPP schedule + NTP shift
  priority           ←    Validation rule
```

---

## VT Formula Parsing

`vt_parser.parse_validation_time()` converts formula string → day offsets:

| Formula | fa_lo | fa_hi | fa_rule | fc_rule |
|---------|-------|-------|---------|---------|
| `start+3M<=FA<=start+5M` | 90 | 150 | ✓ | — |
| `start+8W<=FA<=FC<=start+20W` | 56 | 140 | ✓ | ✓ (same) |
| `start+3M<=FC<=start+5M` | — | — | — | ✓ |
| `start<=FA<=start+2M` | 0 | 60 | ✓ | — |

FC default (when there is no FC rule): `fa_recommended + 60 days ± 15 days`

**FC-only rules with FA submission type (added 2026-06-11):**
When the VT formula only constrains FC (e.g. `start-3M<=FC<=start-1M`) but `sub_type=FA`,
FA is back-calculated from FC:
```
fa_center    = fc_recommended − 60 days
fa_earliest  = fa_center − 15 days
fa_latest    = fa_center + 15 days
fa_recommended = fa_center
notes = "FA derived from FC constraint (FC-only VT rule)"
```
This eliminates `missing_fa` status for these rows.

---

## Activity Matching — Hybrid Workflow (default)

`/schedule/generate` uses `activity_resolver=hybrid` as the default. The hybrid workflow
combines a structured cell search with a full-corpus fallback, always choosing the better result.

### Step 1 — Structured cell search

Derive a `(system, phase)` cell from the MDL row:
- **system** — extracted from Equipment / System / Title tokens via `_SCOPE_ALIASES`
  (e.g. `"Gas Turbine Generator"` → `gtg`, `"HRSG"` → `hrsg`)
- **phase** — derived from Deliverable type and rule keywords
  (e.g. `"P&I DIAGRAM"` → `system_design`, `"FOUNDATION DRAWING"` → `civil_design`)

Within the cell, BM25 + semantic + RRF is run using **local cell ranks** (not global
4039-activity ranks), so activities that rank best within their cell are not penalised by
their lower global position.

### Step 2 — Full-corpus text search

Independently run BM25 + semantic + RRF over all 4039 activities using the same query.

### Step 3 — Quality comparison and selection

```python
if structured_cell_found AND s_qual.adjusted_score >= t_qual.adjusted_score * 1.05:
    use structured result   # resolution_reason = "structured_preferred"
else:
    use text result         # resolution_reason = "structured_cell_found_text_preferred"
                            #                  or "text_only" (no cell found)
```

The 1.05× threshold means structured only wins when it is meaningfully better — not just
marginally. If the structured cell is empty, the text result is used unconditionally.

### Procurement conflict guard

Design-phase documents (`system_design`, `design_drawing`, `design_criteria`, `civil_design`)
must not use procurement-phase activities as anchor. If the structured result is
procurement-phase and the query is design-phase, the structured result is discarded and
the text path is used instead (`resolution_reason = "structured_blocked_procurement_conflict"`).

### Activity quality gate

After selecting the candidate, the result is evaluated before generating dates:

| Block condition | Tag | Bypass available? |
|---|---|---|
| `phase_status == "mismatch"` | `activity_phase_mismatch` | No |
| `scope_status == "mismatch"` | `activity_scope_mismatch` | No |
| `scope_source=="rule"` AND `scope≠match` | `activity_rule_scope_unmatched` | **Yes** — when `activity_unscoped` + `phase∈{match,compatible}` + `sem≥0.55` + `rrf≥0.01` |
| `rrf_score < 0.01` | `activity_rrf_below_gate` | No |
| `generic_activity AND adjusted_score < 0.005` | `activity_generic_low_confidence` | No |
| design-phase doc + procurement-phase activity | `activity_phase_procurement_conflict` | No |

**Unscoped activity bypass** — CCPP contains generic template activities (e.g. `"P&ID"`,
`"(COND System) P&ID & System Design"`) that carry no equipment scope token. These are
correctly matched by semantic similarity but trigger `activity_rule_scope_unmatched` because
the rule's scope cannot be confirmed. The bypass allows them through when the semantic and
RRF scores are both strong, treating the missing scope as a data gap in the activity, not
evidence of a wrong match.

### Debug fields in output

| Field | Meaning |
|---|---|
| `activity_match_resolver_mode` | always `hybrid` |
| `activity_match_resolution_reason` | `structured_preferred` / `structured_cell_found_text_preferred` / `text_only` / `structured_blocked_procurement_conflict` / etc. |
| `activity_match_structured_scope` | derived `(system, phase)` cell key |
| `activity_match_structured_cell_size` | number of activities in the cell (0 = text-only fallback) |
| `activity_match_phase_status` | `match` / `compatible` / `query_unknown` / `mismatch` |
| `activity_match_scope_status` | `match` / `query_unscoped` / `activity_unscoped` / `mismatch` |

---

## Confidence-Graded Output (`schedule_quality_status`)

Instead of hard-blocking uncertain rows, the engine generates dates with a quality flag:

| `date_range_status` | `schedule_quality_status` | Meaning |
|---------------------|--------------------------|---------|
| `generated` | `needs_review` | Dates computed; quality flags present |
| `fi_complete` | `needs_review` | FI doc — no FA needed; FC computed |
| `skip` | `skip` | Rule says SKIP — document excluded |
| `no_rule` | `blocked_no_rule` | No matching validation rule found |
| `blocked_rule` | `blocked_rule` | Rule match quality below gate |
| `blocked_activity` | `blocked_activity` | Activity match quality below gate |
| `blocked_rule_activity` | `blocked_rule_activity` | Both rule and activity below gate |

**Gate thresholds:**
- Rule: block when `rule_score < 0.5` AND NOT semantically confirmed (`family=match` + `subtype=match` + `semantic≥0.60` + `scope≠mismatch`)
- Activity: block when `rrf_score < 0.01` OR (`generic_activity` AND `adjusted_score < 0.005`) OR `scope_status=mismatch` OR `phase_status=mismatch`

**`schedule_quality_reasons`** — semicolon-separated flags on each row explaining quality signals (e.g. `rule_scope_status=rule_generic`, `activity_phase_status=compatible`). Present on all rows including generated ones.

**`schedule_confidence`** — composite score from rule × activity × date components (0–1).
- Rows from **historical MDL** (no `match_score` column): candidate component = 1.0, no penalty.
- Rows from **ITB candidate pipeline** (`mdl_candidates_*.csv`, has `match_score`): candidate component scaled by match_score (0.5–1.0).

---

### Production Confidence Tiers

Use these tiers (derived from rule + activity signals) to decide review depth:

| Tier | Conditions | Recommended action |
|---|---|---|
| **T1 — High confidence** | `rule family=match` + `subtype=match` + `activity phase=match` + `activity scope=match` + `rrf≥0.01` | Use directly |
| **T2 — Medium confidence** | Rule solid + `phase∈{match,compatible}` + scope unconfirmed (unscoped/generic) | Spot-check sample |
| **T3 — Low confidence** | `phase=query_unknown` / `activity_rrf_low` / generic activity / `query_unscoped` | Expert review |

**Benchmark result (Fadhili_MDL_classified.csv, 2682 rows, hybrid mode, 2026-06-12):**

| `date_range_status` | count | % |
|---|---|---|
| `generated` | 1579 | 58.9% |
| `fi_complete` | 450 | 16.8% |
| `skip` | 225 | 8.4% |
| `blocked_activity` | 132 | 4.9% |
| `no_rule` | 144 | 5.4% |
| `blocked_rule` | 144 | 5.4% |
| `blocked_rule_activity` | 8 | 0.3% |

**Usable (generated + fi_complete): 2029 (75.7%)** — Usable + Skip: 2254 (84.1%)



