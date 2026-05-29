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
       └─ schedule_cleaner.py (CLI)
             └─▶ ccpp_guide_schedule_clean.json   (4039 activities, dates, WBS)

 [B] Historical MDL Excel files (*_MDL.xlsx)
       └─ classify_mdl_v5-2.py  (LLM, script)
             └─▶ *_MDL_classified.csv   (Title, Equipment, System, Deliverable)
                   └─ save_to_neo4j_test.py  (script)
                         └─▶ Neo4j: MDL document nodes + HNSW vector index

 [C] ITB PDF
       └─ /parser + /chunker  (API)
             └─▶ ITB chunks JSON  (page, text, hierarchy)
                   └─ test_itb_extraction.py  (LLM, script)
                         └─▶ output_itb_section*.csv
                               (1st–5th Depth, Keywords, Search Query per chunk)
                               └─ match_itb_advanced.py  (Neo4j vector search, script)
                                     └─▶ output_match_*.csv
                                           (each ITB chunk + Matched_Doc_1..20)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 RUNTIME API  src/api/routes/schedule.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  output_match_*.csv
  ┌──────────────────────────────────────────────────────────────────┐
  │  ITB CHUNK side                   MDL DOCUMENT side              │
  │                                                                  │
  │  POST /schedule/map               POST /schedule/candidates      │
  │  ─────────────────                ──────────────────────────     │
  │  ITB chunk → find which           ITB chunk → extract which      │
  │  CCPP guide schedule              MDL documents are needed       │
  │  activity it corresponds to       (parse Matched_Doc_1..N)       │
  │                                                                  │
  │  Output:                          Output:                        │
  │  schedule_mapping_*.json          mdl_candidates_*.csv           │
  │  (activity_id per ITB chunk,      (Title, Equipment, Deliverable │
  │   BM25 + semantic + LLM)          itb_sources, score)            │
  └──────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                               POST /schedule/generate
                               ────────────────────────
                               MDL document → FA/FC dates

                               For each MDL row:
                               1. match validation_rule.csv
                                  normalize(Deliverable) + Equipment
                                  → sub_type: FA / FI / SKIP
                                  → VT formula: start+4W<=FA<=start+6W
                               2. BM25 search guide schedule
                                  → best matching activity
                                  → anchor_date = activity.start_date
                               3. compute date range
                                  fa_earliest = anchor + lo_days
                                  fa_latest   = anchor + hi_days
                                  fc = fa_recommended + 60 days

                               Output:
                               generated_schedule_*.json/xlsx
                               (document_no, title, equipment,
                                submission_type FA/FI,
                                fa_earliest / fa_recommended / fa_latest,
                                fc_earliest / fc_recommended / fc_latest,
                                itb_sources ← traceability back to ITB)
```

---

## /schedule/map in detail

```
INPUT: output_match_*.csv
  Each row = 1 ITB chunk
  Columns: Document, Page, Search Query, Keywords, Depth_Context, Matched_Doc_1..20

  ┌─────────────────────────────────────────────────────────────────┐
  │  schedule_loader                                                │
  │  ccpp_guide_schedule_clean.json → List[ScheduleActivity]        │
  │  4039 activities with: activity_id, name, wbs_path,            │
  │                        start_date, finish_date, target_text     │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
  ┌──────────────────────────▼──────────────────────────────────────┐
  │  BM25Index(target_text for each activity)                       │
  │  SemanticIndex(Azure OpenAI embed all 4039 activities)  ← slow  │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
  For each ITB row:
  query = row["Search Query"]   e.g. "Heat Recovery Steam Generator natural circulation"
                             │
  ┌──────────────────────────▼──────────────────────────────────────┐
  │  BM25.score(query)  → [score, score, ...] × 4039               │
  │  Semantic.score(query) → embed query → cosine sim × 4039        │
  │  rrf_candidates() → merge via Reciprocal Rank Fusion → top 10  │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
  ┌──────────────────────────▼──────────────────────────────────────┐
  │  ScheduleLLMValidator.select_activity(query, top_10_candidates) │
  │  → LLM picks best: selected_activity_id, confidence, reason     │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
OUTPUT: schedule_mapping_*.json
  Each row = 1 ITB chunk + selected activity
  { document, search_query, llm_selected_activity_id,
    llm_confidence, candidate_1..10 with scores }
```

---

## /schedule/candidates in detail

```
INPUT: output_match_*.csv  (same file as /schedule/map)
  Uses Matched_Doc_1..20 columns (results of Neo4j vector search)

  Matched_Doc_N format:
  "[Fadhili] GTG - P&I DIAGRAM FOR COOLING AIR COOLER (최종점수: 0.91 / 기본: 0.74)"
   ─────────  ───   ─────────────────────────────────  ──────────────────────────
   [Project]  Equip Title                              Score

  For each ITB row, for each Matched_Doc_1..N:
  ┌─────────────────────────────────────────────────────────────────┐
  │  if final_score >= threshold (default 0.85):                   │
  │    parse doc name:                                              │
  │      strip [Project], strip score suffix                       │
  │      split on " - ": equipment | title                         │
  │      extract deliverable from title keywords                   │
  │        e.g. "P&I DIAGRAM" in title → deliverable = "P&I DIAG" │
  │    deduplicate by (equipment, deliverable, title)              │
  │    accumulate itb_sources for traceability                     │
  └─────────────────────────────────────────────────────────────────┘

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
  │  schedule_loader → 4039 ScheduleActivity                       │
  │  RuleTable.load(validation_rule.csv) → 5918 rules              │
  │  BM25Index(activity.target_text)                               │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
  For each MDL row:

  Step 1: Rule matching
  ┌──────────────────────────▼──────────────────────────────────────┐
  │  norm_del = _DELIVERABLE_NORM["P&I DIAGRAM"] → "P&ID"          │
  │  scope    = Equipment or System or Building                     │
  │  query    = "P&ID for Gas Turbine Generator"                   │
  │                                                                 │
  │  RuleTable.match(query)  → Jaccard overlap vs 5918 rules       │
  │    rule.sub_type  = "FA"                                        │
  │    rule.vt_parsed = {fa_lo_days:84, fa_hi_days:126}            │
  │    rule.priority  = 1  (1=specific → confidence 0.9)           │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
  Step 2: Activity matching
  ┌──────────────────────────▼──────────────────────────────────────┐
  │  activity_query = Equipment + System + norm_del + Title        │
  │  BM25.score(activity_query) → argmax → top-1 activity          │
  │  anchor_date = activity.start_date  (or finish_date if         │
  │                rule.activity_keywords ∩ {delivery, fob, ...})  │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
  Step 3: Date range
  ┌──────────────────────────▼──────────────────────────────────────┐
  │  compute_date_range(vt_parsed, anchor, sub_type, priority)     │
  │                                                                 │
  │  fa_earliest    = anchor + fa_lo_days  (e.g. +84d)             │
  │  fa_latest      = anchor + fa_hi_days  (e.g. +126d)            │
  │  fa_recommended = midpoint                                     │
  │  fc_recommended = fa_recommended + 60d  (default)              │
  │  confidence     = 0.9 / 0.6 / 0.3  by priority                │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
OUTPUT: generated_schedule_*.json
  { document_no, title, equipment, deliverable,
    itb_sources,           ← traceability: which ITB chunks need this doc
    submission_type,       ← FA / FI / SKIP
    matched_activity_id,
    matched_activity_name,
    fa_earliest, fa_recommended, fa_latest,
    fc_earliest, fc_recommended, fc_latest,
    date_range_status,     ← generated / skip / no_rule / missing_date
    date_range_confidence  ← 0.90 / 0.60 / 0.30
  }
```

---

## Connection between ITB chunk and MDL document

```
ITB chunk (one technical requirement)
  │
  │  Neo4j vector search (match_itb_advanced.py)
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
1. /schedule/map output is not connected to /schedule/generate
   - /schedule/map finds activity_id per ITB chunk via LLM
   - /schedule/generate finds activity via BM25 per MDL doc independently
   - Future: use /schedule/map activity_id as anchor instead of BM25

2. Anchor date = guide schedule template (2007–2009)
   - ScheduleActivity.po_finish_date always ""
   - Needs client-provided PO date mapping per project

3. ITB workflow (chunking, extraction, Neo4j matching) not in src/ API
   - Still standalone scripts in 00_current_work/current_test_env/

4. No final MDL Excel formatter
   - generated_schedule_*.xlsx is an internal table, not the client deliverable
```
