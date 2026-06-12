# System Architecture

## What the system does

Given an ITB (client requirements PDF) and historical MDL references, automatically produce
a schedule showing when each technical document must be submitted (FA date, FC date).

---

## The two source inputs

```
┌─────────────────────────────────────┐   ┌──────────────────────────────────────────┐
│              ITB                    │   │              MDL                          │
│  (Invitation To Bid)                │   │  (Master Document List)                  │
│                                     │   │                                          │
│  PDF from client describing         │   │  Excel from historical CCPP projects:    │
│  project requirements:              │   │  Fadhili, Grati, Karabatan,              │
│  - power output specs               │   │  Muara Tawar, R&N, Turkistan, Ukudu     │
│  - equipment requirements           │   │                                          │
│  - civil/structural scope           │   │  Each row = one deliverable document:    │
│  - commissioning tests              │   │  Document No | Title | Equipment         │
│                                     │   │  System | Building | Deliverable         │
│  Does NOT say "produce P&ID         │   │                                          │
│  for HRSG" — that must be inferred  │   │  Stored in Neo4j with embeddings         │
│  by matching to MDL references      │   │  for vector search                       │
└─────────────────────────────────────┘   └──────────────────────────────────────────┘
            │                                             │
            └──────────────── CONNECT ────────────────────┘
                          (this system's job)
```

---

## Full pipeline

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 OFFLINE PREP (run once, results stored on disk)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 [A] CCPP guide schedule XLSX
       └─ data_prep/ccpp_schedule_cleaner.py (CLI)
             └─▶ ccpp_guide_schedule_260527_clean.json   (4039 activities, dates, WBS)

 [B] Historical MDL Excel files (*_MDL.xlsx)
       └─ uv run mdl-classify  (LLM CLI)
             └─▶ *_MDL_classified.csv   (Title, Equipment, System, Deliverable)
                   └─ uv run mdl-ingest  (CLI)
                         └─▶ Neo4j: MDL document nodes + HNSW vector index

 [C] ITB PDF
       └─ /parser + /chunker  (API)
             └─▶ ITB chunks JSON  (page, text, hierarchy)
                   └─ uv run itb-extract  (LLM CLI)
                         └─▶ itb_extraction_section*.csv
                               (1st–5th Depth, Keywords, Search Query per chunk)
                               └─ uv run itb-match  (Neo4j vector search CLI)
                                     └─▶ output_match_*.csv
                                           (each ITB chunk + Matched_Doc_1..20)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 RUNTIME API  src/api/routes/schedule.py   (two endpoints)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  output_match_*.csv
  ┌──────────────────────────────────────────────────────────────────┐
  │  POST /schedule/candidates                                       │
  │  ──────────────────────────                                      │
  │  ITB chunk → extract which MDL documents are needed              │
  │  (parse Matched_Doc_1..N, filter by score, dedup)               │
  │  optional classify_with_llm → fill Equipment/Deliverable        │
  │                                                                  │
  │  Output: mdl_candidates_*.csv                                    │
  │  (Title, Equipment, Deliverable, itb_sources, match_score)      │
  └──────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                               POST /schedule/generate
                               ────────────────────────
                               MDL document → FA/FC dates

                               For each MDL row:
                               1. match Validation Rule:
                                  normalize(Deliverable) + " for " + Equipment
                                  → sub_type: FA / FI / SKIP
                                  → VT formula: start+4W<=FA<=start+6W
                                  hybrid token+embedding (always)
                               2. search CCPP Guide Schedule for activity:
                                  BM25+semantic+RRF (always)
                                  → anchor_date = activity.start/finish_date
                                  → + NTP shift if ntp_date provided
                               3. compute date range:
                                  fa_earliest = anchor + lo_days
                                  fa_latest   = anchor + hi_days
                                  fc = fa_recommended + 60 days (or FC formula)

                               Output:
                               generated_schedule_*.json/xlsx
                               (document_no, title, equipment,
                                submission_type FA/FI,
                                fa_earliest / fa_recommended / fa_latest,
                                fc_earliest / fc_recommended / fc_latest,
                                itb_sources ← traceability back to ITB)
```
---

## /schedule/candidates in detail

```
INPUT: output_match_*.csv  (ITB→MDL Neo4j matching output)
  Uses Matched_Doc_1..20 columns (results of Neo4j vector search)

  Matched_Doc_N format:
  "[Fadhili] GTG - P&I DIAGRAM FOR COOLING AIR COOLER (최종점수: 0.91 / 기본: 0.74)"
   ─────────  ───   ─────────────────────────────────  ──────────────────────────
   [Project]  Equip Title                              Score

  For each ITB row, for each Matched_Doc_1..N:
  ┌─────────────────────────────────────────────────────────────────┐
  │  score = Semantic (new format, 0–1) or 최종점수/Vector (old)    │
  │  if score >= threshold (default 0.75; old format → 0.85):      │
  │    parse doc name:                                              │
  │      strip [Project], strip score suffix                       │
  │      split on " - ": equipment | title                         │
  │      extract deliverable from title keywords                   │
  │        e.g. "P&I DIAGRAM" in title → deliverable = "P&I DIAG" │
  │    deduplicate by (equipment, deliverable, title)              │
  │    accumulate itb_sources for traceability                     │
  └─────────────────────────────────────────────────────────────────┘

  optional classify_with_llm=true:
    for candidates still missing Equipment/Deliverable after regex,
    call the MDL LLM classifier (batched, parallel, disk-cached by title)

OUTPUT: mdl_candidates_*.csv
  Compatible with *_MDL_classified.csv format + extra columns:
  Source File | Document No | Title | Equipment | Deliverable | ...
  match_score | itb_sources

  itb_sources example:
  "R&N_ITB:p97(score=0.93) | R&N_ITB:p98(score=0.91)"
  ← shows which ITB chunks triggered this MDL document candidate
```

---

## /schedule/generate in detail

```
INPUT: *_MDL_classified.csv  OR  mdl_candidates_*.csv
  Each row = 1 MDL document
  Columns: Title, Equipment, System, Building, Deliverable, (itb_sources)

  ┌─────────────────────────────────────────────────────────────────┐
  │  get_schedule_activities → 4039 ScheduleActivity  (memoized)    │
  │  get_rule_matcher(validation_rule_clean.csv)      (memoized)    │
  │  get_bm25_index(activity.target_text)             (memoized)    │
  │  (resource_cache: built once per process, keyed by path+mtime)  │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
  Three passes (matching done up-front, then rendered):

  Pass 1: Rule matching  (resolve_rules)
  ┌──────────────────────────▼──────────────────────────────────────┐
  │  norm_del  = normalize_deliverable("P&I DIAGRAM") → "P&ID"      │
  │  scope     = Equipment or System or Building                    │
  │  query     = "P&ID for GTG"   (equipment_to_abbr applied)       │
  │                                                                 │
  │  hybrid token+embedding (always, mandatory):                    │
  │    token·(1−w) + semantic·w  (w=0.3), × priority_weight, thr 0.2 │
  │    token = |kw ∩ doc| / max(|kw|,3)                             │
  │    rule.sub_type  = "FA"                                        │
  │    rule.vt_parsed = {fa_lo_days:84, fa_hi_days:126}             │
  │    rule.priority  = 1  (1=specific → confidence 0.9)            │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
  Pass 2: Activity matching  (resolve_activities)
  ┌──────────────────────────▼──────────────────────────────────────┐
  │  activity_query = Equipment + System + norm_del + Title         │
  │                   + phase boost (deliverable / rule keyword)    │
  │                                                                 │
  │  Hybrid resolver (default):                                     │
  │    1. Structured: derive (system,phase) cell → local BM25+      │
  │       semantic+RRF within cell                                  │
  │    2. Text: BM25+semantic+RRF over all 4039 activities          │
  │    3. Use structured if adjusted_score ≥ text × 1.05,           │
  │       else use text; procurement conflict → force text          │
  │                                                                 │
  │  → top-1 activity selected                                      │
  │  anchor_date = activity.start_date  (or finish_date if          │
  │                rule.activity_keywords ∩ {delivery, fob, ...})   │
  │  if ntp_date: anchor += (ntp_date − 2007-03-01)                 │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
  Pass 3: Date range
  ┌──────────────────────────▼──────────────────────────────────────┐
  │  compute_date_range(vt_parsed, anchor, sub_type, priority)      │
  │                                                                 │
  │  fa_earliest    = anchor + fa_lo_days  (e.g. +84d)              │
  │  fa_latest      = anchor + fa_hi_days  (e.g. +126d)             │
  │  fa_recommended = midpoint                                      │
  │  fc_recommended = fa_recommended + 60d  (default)               │
  │  FC-only rule + sub_type=FA → FA = fc_recommended − 60d ± 15d   │
  │  confidence     = 0.9 / 0.6 / 0.3  by priority                  │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
OUTPUT: generated_schedule_*.json
  { document_no, title, equipment, deliverable,
    itb_sources,              ← traceability: which ITB chunks need this doc
    submission_type,          ← FA / FI / SKIP
    matched_activity_id,
    matched_activity_name,
    fa_earliest, fa_recommended, fa_latest,
    fc_earliest, fc_recommended, fc_latest,
    date_range_status,        ← generated / fi_complete / skip / no_rule /
                                 missing_date / blocked_rule / blocked_activity /
                                 blocked_rule_activity
    schedule_quality_status,  ← needs_review / blocked_rule / blocked_activity /
                                 blocked_rule_activity / blocked_no_rule / skip
    schedule_quality_reasons, ← list of quality flags
    schedule_confidence,      ← composite confidence score
    activity_match_resolver_mode,      ← text / structured / hybrid
    activity_match_resolution_reason,  ← structured_preferred / text_only / etc.
  }
```

---

## Connection between ITB chunk and MDL document

```
ITB chunk (one technical requirement)
  │
  │  Neo4j vector search (uv run itb-match)
  │  embeds Search Query → finds similar MDL docs from historical projects
  │
  ├─▶ Matched_Doc_1  [Fadhili] GTG - P&I DIAGRAM (score 0.93)
  ├─▶ Matched_Doc_2  [Muara Tawar] GTG - P&ID COOLING (score 0.91)
  ├─▶ Matched_Doc_3  [Fadhili] GTG - SYSTEM DESCRIPTION (score 0.88)
  │   ...
  └─▶ Matched_Doc_20 ...
            │
            │  /schedule/candidates  (parse + deduplicate)
            │
            ▼
  MDL document candidate
  { title: "P&I DIAGRAM FOR COOLING AIR COOLER",
    equipment: "Gas Turbine Generator",
    deliverable: "P&I DIAGRAM",
    itb_sources: "R&N_ITB:p97(score=0.93) | R&N_ITB:p98(score=0.91)" }
            │
            │  /schedule/generate  (rule match + BM25 + date compute)
            │
            ▼
  Schedule entry
  { title: "P&I DIAGRAM FOR COOLING AIR COOLER",
    submission_type: "FA",
    fa_recommended: "2024-08-15",
    fc_recommended: "2024-10-14",
    itb_sources: "R&N_ITB:p97(score=0.93) | ..."  ← preserved
  }
```

The `itb_sources` column is the end-to-end traceability link:
- tells you which page(s) of the ITB triggered each MDL document
- preserved through candidates → generate

---

## Known architectural gaps

```
1. NTP shift, not real PO dates
   - Template dates (anchored at 2007-03-01) are linearly shifted by a single
     ntp_date offset. This is an improvement over raw template dates but still
     assumes the whole schedule scales from one NTP; per-activity client PO dates
     are not yet mapped. ScheduleActivity.po_finish_date always "".

2. ITB chunk → activity mapping is no longer a route
   - The old /schedule/map (LLM activity selection per ITB chunk) was removed.
   - /schedule/generate finds the activity via BM25 (or BM25+semantic+RRF) per MDL
     document independently. There is no LLM-validated activity selection anymore.

3. ITB workflow (chunking, extraction, Neo4j matching) is CLI-first, not fully
   exposed as API routes — use `uv run itb-extract` and `uv run itb-match`.

4. No final MDL Excel formatter
   - generated_schedule_*.xlsx is an internal table, not the client deliverable.
```