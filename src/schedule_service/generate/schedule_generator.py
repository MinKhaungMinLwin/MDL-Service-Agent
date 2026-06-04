"""Generate FA/FC date ranges from MDL classified documents."""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from datetime import date, timedelta

from loguru import logger

from schedule_service.generate.activity_matching.ccpp_schedule_loader import (
    DEFAULT_SCHEDULE_PATH,
    load_schedule_activities,
)
from schedule_service.generate.activity_matching.keyword_search import BM25Index
from schedule_service.generate.activity_matching.reranker import rrf_candidates
from schedule_service.generate.activity_matching.semantic_search import SemanticIndex
from schedule_service.generate.date_computation.date_range_engine import DateRange, compute_date_range
from schedule_service.generate.rule_matching.rule_loader import DEFAULT_RULE_PATH, RuleTable, ValidationRule
from schedule_service.models import ScheduleActivity
from schedule_service.normalizer import equipment_to_abbr, normalize_deliverable
from schedule_service.output_writer import write_schedule_outputs

DEFAULT_OUTPUT_DIR = Path("output/schedule_service/generate")

# All dates in the CCPP guide schedule are relative to this template NTP
TEMPLATE_NTP = date(2007, 3, 1)

# --- Activity-phase steering (query-time retrieval logic, not data normalization) ---

# Activity keywords that indicate the activity finish_date should be the VT anchor.
_FINISH_DATE_KEYWORDS = {"transportation", "delivery", "fob", "manufacturing", "fo b"}

# Rule activity_keywords → BM25 phase-boost terms, steering activity selection
# to the correct project phase (early design, delivery, commissioning, etc.).
_ACTIVITY_KW_BOOST: dict[str, str] = {
    "p.o":           "P.O Procurement",
    "po":            "P.O Procurement",
    "pof":           "P.O Procurement finish",
    "delivery":      "transportation delivery",
    "fob":           "transportation delivery FOB",
    "transportation":"transportation delivery",
    "manufacturing": "manufacturing P.O",
    "fo b":          "transportation delivery",
    "commissioning": "commissioning test",
}

# Deliverable type → BM25 phase-boost terms. Takes priority over the rule's keyword
# boost so a wrong rule match cannot pull activity selection to the wrong phase.
_DELIVERABLE_PHASE_BOOST: dict[str, str] = {
    "DESIGN CRITERIA":    "Design Criteria engineering",
    "SYSTEM DESCRIPTION": "System Description P&ID",
    "LAYOUT":             "Layout Arrangement Drawing",
    "OVERVIEW":           "System Description overview",
}


@dataclass(frozen=True)
class MatchContext:
    """The validation rule and CCPP guide schedule activity resolved for one MDL row.

    Produced up-front by _resolve_rules + _resolve_activities so that
    _format_schedule_row only renders output and never re-runs matching.
    """

    rule: ValidationRule | None
    activity: ScheduleActivity


def generate_schedule_file(
    input_csv: Path,
    schedule_activities: list[ScheduleActivity],
    output_dir: Path,
    rule_path: Path = DEFAULT_RULE_PATH,
    limit: int = 0,
    ntp_date: str = "",
    semantic_cache_dir: Path | None = None,
    semantic_weight: float = 0.3,
    use_semantic_activities: bool = False,
    activity_cache_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Generate FA/FC date ranges from an MDL classified CSV.

    Args:
        ntp_date:           Real project NTP date in ISO format (e.g. "2024-01-15").
                            Shifts all guide schedule template dates accordingly.
        semantic_cache_dir: If provided, builds/loads a semantic rule index and uses
                            hybrid (token + embedding) scoring for rule matching.
                            Embeddings are cached under this directory.
        semantic_weight:    Weight of semantic score in hybrid scoring (0–1, default 0.3).
                            Kept low so the 76 WTS rules can't semantically dominate
                            generic queries that have weak token overlap.
    """
    _log(f"Reading MDL classified CSV: {input_csv}")
    rows = _read_csv(input_csv)
    original_count = len(rows)
    if limit > 0:
        rows = rows[:limit]
        _log(f"Limit enabled: processing first {len(rows)} of {original_count} rows")
    if not rows:
        raise ValueError(f"No rows found in {input_csv}")

    shift_days = _compute_shift(ntp_date)
    if shift_days:
        _log(f"NTP shift: {ntp_date} → {shift_days:+d} days from template NTP {TEMPLATE_NTP}")
    else:
        _log("No NTP date provided — using guide schedule template dates")

    rule_table = _load_rule_table(rule_path)

    _log(f"Building BM25 index for {len(schedule_activities)} schedule activities")
    bm25 = BM25Index([a.target_text for a in schedule_activities])

    # 1. Resolve the validation rule for every row (semantic hybrid or token).
    rules = _resolve_rules(rows, rule_table, semantic_cache_dir, semantic_weight)

    # 2. Resolve the CCPP activity for every row (BM25, or BM25+semantic+RRF), rule-boosted.
    activities = _resolve_activities(
        rows, schedule_activities, bm25, rules,
        use_semantic_activities=use_semantic_activities,
        activity_cache_dir=activity_cache_dir or output_dir / "activity_semantic_cache",
    )

    # 3. Render output rows from the resolved matches.
    contexts = [MatchContext(rule=r, activity=a) for r, a in zip(rules, activities, strict=True)]
    output_rows = [
        _format_schedule_row(row, ctx, shift_days)
        for row, ctx in zip(rows, contexts, strict=True)
    ]

    output_stem = _output_stem(input_csv)
    if ntp_date:
        output_stem = f"{output_stem}_ntp{ntp_date}"
    if limit > 0:
        output_stem = f"{output_stem}_limit{limit}"
    _log(f"Writing generated schedule with stem: {output_stem}")
    return write_schedule_outputs(output_dir, output_stem, output_rows)


def _resolve_rules(
    rows: list[dict[str, str]],
    rule_table: RuleTable | None,
    semantic_cache_dir: Path | None,
    semantic_weight: float,
) -> list[ValidationRule | None]:
    """Resolve the validation rule for every row, one strategy per request.

    - no rule table        → all None (graceful degradation)
    - semantic cache dir    → hybrid token + embedding match
    - otherwise             → token match (rule_query, then title fallback)
    """
    if rule_table is None:
        return [None] * len(rows)
    if semantic_cache_dir:
        return _match_rules_semantic(rows, rule_table, semantic_cache_dir, semantic_weight)
    return _token_match_rules(rows, rule_table)


def _resolve_activities(
    rows: list[dict[str, str]],
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    rules: list[ValidationRule | None],
    *,
    use_semantic_activities: bool,
    activity_cache_dir: Path,
) -> list[ScheduleActivity]:
    """Resolve the CCPP guide schedule activity for every row.

    Uses BM25 + semantic + RRF when enabled, else plain BM25 top-1. Either way the
    activity query is rule-boosted via _build_activity_query.
    """
    if use_semantic_activities:
        _log("Building semantic activity index ...")
        semantic_index = SemanticIndex.build(activities, activity_cache_dir)
        return _match_activities_semantic(rows, activities, bm25, semantic_index, rules)
    return [
        _bm25_top1_activity(row, rule, activities, bm25)
        for row, rule in zip(rows, rules, strict=True)
    ]


def _bm25_top1_activity(
    row: dict[str, str],
    rule: ValidationRule | None,
    activities: list[ScheduleActivity],
    bm25: BM25Index,
) -> ScheduleActivity:
    """Return the single best activity by BM25 score for a rule-boosted query."""
    bm25_scores = bm25.score(_build_activity_query(row, rule))
    top_idx = max(range(len(bm25_scores)), key=lambda idx: bm25_scores[idx])
    return activities[top_idx]


def _match_rules_semantic(
    rows: list[dict[str, str]],
    rule_table: RuleTable,
    cache_dir: Path,
    semantic_weight: float,
) -> list[ValidationRule | None]:
    """Batch-embed all rule queries and return hybrid-matched rules for each row."""
    from common.embedding_client import AzureEmbeddingService
    from schedule_service.generate.rule_matching.rule_semantic import RuleSemanticIndex

    semantic_index = RuleSemanticIndex.build(rule_table.rules, cache_dir)

    # Compute (rule_query, title) for every row — same logic as _format_schedule_row
    query_pairs: list[tuple[str, str]] = []
    for row in rows:
        query_pairs.append((_build_rule_query(row), row.get("Title", "").strip()))

    # Deduplicate queries to minimise embedding API calls
    all_queries = [q for pair in query_pairs for q in pair]
    unique_queries = list(dict.fromkeys(all_queries))
    _log(f"Semantic rule matching: embedding {len(unique_queries)} unique queries for {len(rows)} rows")

    import numpy as np

    service = AzureEmbeddingService()
    raw_embeddings = service.embed_texts(unique_queries)

    # Bulk matmul: (n_unique, dims) @ (dims, n_rules) → (n_unique, n_rules)
    # L2-normalise query matrix rows so dot-product == cosine similarity
    query_matrix = np.array(raw_embeddings, dtype=np.float32)
    norms = np.linalg.norm(query_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    query_matrix /= norms
    all_sims = semantic_index.score_matrix(query_matrix)  # (n_unique, n_rules)

    query_to_idx = {q: i for i, q in enumerate(unique_queries)}

    def _get_sims(query: str) -> list[float]:
        return all_sims[query_to_idx[query]].tolist()

    results: list[ValidationRule | None] = []
    for rule_query, title in query_pairs:
        rule = rule_table.match_with_embedding(rule_query, _get_sims(rule_query),
                                               semantic_weight=semantic_weight)
        if rule is None:
            rule = rule_table.match_with_embedding(title, _get_sims(title),
                                                   semantic_weight=semantic_weight)
        results.append(rule)

    return results


def _build_rule_query(row: dict[str, str]) -> str:
    """Build the validation-rule match query: normalize(Deliverable) + 'for' + abbreviated scope.

    Single source of truth — used for both pre-matching (semantic/token) and the
    per-row format step so the query string can never drift between passes.
    """
    norm_del = normalize_deliverable(row.get("Deliverable", "").strip())
    scope = (
        row.get("Equipment", "").strip()
        or row.get("System", "").strip()
        or row.get("Building", "").strip()
    )
    abbr_scope = equipment_to_abbr(scope)
    return f"{norm_del} for {abbr_scope}" if abbr_scope else norm_del


def _build_activity_query(row: dict[str, str], rule: ValidationRule | None) -> str:
    """Build a BM25/RRF query for activity matching, with optional rule phase-boost."""
    equipment = row.get("Equipment", "").strip()
    system = row.get("System", "").strip()
    title = row.get("Title", "").strip()
    norm_del = normalize_deliverable(row.get("Deliverable", "").strip())
    query = " ".join(p for p in [equipment, system, norm_del, title] if p)

    # Deliverable-type phase boost takes priority over the rule's keyword boost.
    deliverable_boost = _deliverable_phase_boost(row.get("Deliverable", "").strip())
    if deliverable_boost:
        query = f"{query} {deliverable_boost}"
    elif rule:
        boost = _activity_keyword_boost(rule.activity_keywords)
        if boost:
            query = f"{query} {boost}"
    return query


def _deliverable_phase_boost(deliverable: str) -> str:
    """BM25 phase-boost terms implied by the deliverable type ("" if none)."""
    return _DELIVERABLE_PHASE_BOOST.get(deliverable.strip().upper(), "")


def _activity_keyword_boost(activity_keywords: list[str]) -> str:
    """BM25 phase-boost terms derived from a rule's activity_keywords ("" if none)."""
    terms = [
        _ACTIVITY_KW_BOOST[kw.lower().strip()]
        for kw in activity_keywords
        if kw.lower().strip() in _ACTIVITY_KW_BOOST
    ]
    return " ".join(terms)


def _uses_finish_anchor(activity_keywords: list[str]) -> bool:
    """True if a rule's activity keywords indicate finish_date should anchor the VT formula."""
    return bool({k.lower() for k in activity_keywords} & _FINISH_DATE_KEYWORDS)


def _token_match_rules(
    rows: list[dict[str, str]], rule_table: RuleTable
) -> list[ValidationRule | None]:
    """Token-based rule match for every row (used to build activity queries when semantic rules disabled)."""
    results: list[ValidationRule | None] = []
    for row in rows:
        rule_query = _build_rule_query(row)
        title = row.get("Title", "").strip()
        results.append(rule_table.match(rule_query) or rule_table.match(title))
    return results


def _match_activities_semantic(
    rows: list[dict[str, str]],
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    semantic_index: SemanticIndex,
    rules: list[ValidationRule | None],
) -> list[ScheduleActivity]:
    """Batch-embed activity queries and return RRF top-1 activity for each row.

    Semantic scoring uses a single numpy matrix multiply over all unique queries,
    avoiding per-row Python dot-product loops over 4039 × 1536 dimensions.
    """
    import numpy as np

    from common.embedding_client import AzureEmbeddingService

    activity_queries = [_build_activity_query(row, rule) for row, rule in zip(rows, rules, strict=True)]

    unique_queries = list(dict.fromkeys(activity_queries))
    _log(f"Semantic activity matching: embedding {len(unique_queries)} unique queries for {len(rows)} rows")

    service = AzureEmbeddingService()
    raw_embeddings = service.embed_texts(unique_queries)

    # One matrix multiply: (n_unique_queries, dims) @ (dims, n_activities) → (n_unique_queries, n_activities)
    query_matrix = np.array(raw_embeddings, dtype=np.float32)
    all_semantic_scores = semantic_index.score_matrix(query_matrix)  # shape: (n_unique, n_activities)

    query_to_idx = {q: i for i, q in enumerate(unique_queries)}

    results: list[ScheduleActivity] = []
    for query in activity_queries:
        q_idx = query_to_idx[query]
        bm25_scores = bm25.score(query)
        semantic_scores = all_semantic_scores[q_idx].tolist()
        candidates = rrf_candidates(
            activities=activities,
            bm25_scores=bm25_scores,
            semantic_scores=semantic_scores,
            retrieve_k=50,
            top_k=1,
            has_semantic=True,
        )
        results.append(candidates[0].activity)
    return results


def _format_schedule_row(
    row: dict[str, str],
    ctx: MatchContext,
    shift_days: int = 0,
) -> dict[str, Any]:
    """Format one generated schedule row with FA/FC date ranges from a resolved match."""
    title = row.get("Title", "").strip()
    deliverable = row.get("Deliverable", "").strip()
    equipment = row.get("Equipment", "").strip()
    system = row.get("System", "").strip()
    building = row.get("Building", "").strip()

    rule_query = _build_rule_query(row)
    rule = ctx.rule
    activity = ctx.activity

    sub_type = rule.sub_type if rule else ""
    rule_name = rule.item_name if rule else ""
    vt_parsed: dict = rule.vt_parsed if rule else {}

    # Compute FA/FC date ranges
    dr = DateRange()
    date_range_status = "no_rule"
    if rule and sub_type == "SKIP":
        date_range_status = "skip"
    elif rule:
        anchor = _resolve_anchor_date(activity.start_date, activity.finish_date, rule, shift_days)
        ntp_floor = TEMPLATE_NTP + timedelta(days=shift_days) if shift_days else None
        dr = compute_date_range(vt_parsed, anchor, sub_type, rule.priority, ntp_floor=ntp_floor)
        date_range_status = "generated" if anchor is not None else "missing_date"

    return {
        "source_file": row.get("Source File", ""),
        "document_no": row.get("Document No", "").strip(),
        "title": title,
        "deliverable": deliverable,
        "equipment": equipment,
        "system": system,
        "building": building,
        "itb_sources": row.get("itb_sources", ""),
        "rule_query": rule_query,
        "matched_rule": rule_name,
        "submission_type": sub_type,
        "matched_activity_id": activity.activity_id,
        "matched_activity_name": activity.activity_name_clean or activity.activity_name,
        "matched_activity_wbs_path": activity.wbs_path,
        "matched_activity_start_date": activity.start_date,
        "matched_activity_finish_date": activity.finish_date,
        "fa_earliest": _fmt_date(dr.fa_earliest),
        "fa_recommended": _fmt_date(dr.fa_recommended),
        "fa_latest": _fmt_date(dr.fa_latest),
        "fc_earliest": _fmt_date(dr.fc_earliest),
        "fc_recommended": _fmt_date(dr.fc_recommended),
        "fc_latest": _fmt_date(dr.fc_latest),
        "date_range_status": date_range_status,
        "date_range_confidence": f"{dr.confidence:.2f}" if dr.confidence else "",
        "ntp_shift_days": shift_days if shift_days else "",
    }


def _load_rule_table(path: Path) -> RuleTable | None:
    """Load rule table; return None if file is missing (graceful degradation)."""
    if not path.exists():
        _log(f"Validation rule file not found: {path} — date ranges will be skipped")
        return None
    table = RuleTable.load(path)
    _log(f"Loaded {len(table.rules)} validation rules from {path}")
    return table


def _resolve_anchor_date(
    start_date_str: str,
    finish_date_str: str,
    rule: ValidationRule,
    shift_days: int = 0,
) -> date | None:
    """Pick start_date or finish_date as anchor, then apply NTP shift."""
    use_finish = _uses_finish_anchor(rule.activity_keywords)
    date_str = finish_date_str if use_finish else start_date_str
    if not date_str:
        # Fallback to the other date when the preferred anchor is empty
        # (e.g. MPS "Issue" activities have no start_date but do have finish_date).
        date_str = start_date_str if use_finish else finish_date_str
    if not date_str:
        return None
    try:
        template_date = date.fromisoformat(date_str)
        return template_date + timedelta(days=shift_days)
    except ValueError:
        return None


def _compute_shift(ntp_date: str) -> int:
    """Return days to shift guide schedule dates given a real project NTP date."""
    if not ntp_date:
        return 0
    try:
        return (date.fromisoformat(ntp_date) - TEMPLATE_NTP).days
    except ValueError:
        logger.warning("Invalid ntp_date '{}' — using template dates", ntp_date)
        return 0


def _fmt_date(d: date | None) -> str:
    return d.isoformat() if d is not None else ""


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read an MDL classified CSV file."""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _output_stem(input_csv: Path) -> str:
    """Build the generated schedule output stem."""
    return f"generated_schedule_{input_csv.stem}"


def main() -> None:
    """Run the schedule generator CLI."""
    parser = argparse.ArgumentParser(description="Generate FA/FC date ranges from MDL classified CSV files.")
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N rows from each input CSV.")
    parser.add_argument(
        "--ntp-date",
        default="",
        help="Real project NTP date in ISO format (e.g. 2024-01-15). Shifts all guide schedule dates accordingly.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="One or more *_MDL_classified.csv files.")
    args = parser.parse_args()

    _log(f"Loading schedule activities: {args.schedule}")
    activities = load_schedule_activities(args.schedule)
    _log(f"Loaded {len(activities)} schedule activities")
    for input_csv in args.inputs:
        xlsx_path, json_path = generate_schedule_file(
            input_csv=input_csv,
            schedule_activities=activities,
            output_dir=args.output_dir,
            limit=args.limit,
            ntp_date=args.ntp_date,
        )
        logger.info("Wrote generated schedule workbook: {}", xlsx_path)
        logger.info("Wrote generated schedule JSON: {}", json_path)


def _log(message: str) -> None:
    """Log a schedule generator message."""
    logger.info(message)


if __name__ == "__main__":
    main()
