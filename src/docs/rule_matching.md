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

File: `04_data/schedule_sources/rules/validation_rule.csv` (semicolon-delimited, 5918 rows)

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
fa / ap / fa/fi  → "FA"
fi / if / ifi    → "FI"
as built / unmatch → "SKIP"  ← document does not need scheduling
unknown value    → "SKIP"    ← default when unable to map
```

**Match algorithm (Jaccard):**
```python
score = |kw_tokens ∩ doc_tokens| / |kw_tokens|
# threshold = 0.5 — best score wins, ties broken by lowest priority
```

---

## CCPP Guide Schedule — Structure and Anchor Date

File: `04_data/schedule_sources/processed/ccpp_guide_schedule_260527_clean.json` (4039 activities)

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

**Anchor date selection** (`activity_base_date_policy.csv`):
```
activity keyword contains "transportation/delivery/fob/manufacturing"
  → use activity.finish_date
otherwise
  → use activity.start_date
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
                          → BM25.score() → top-1 activity

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

