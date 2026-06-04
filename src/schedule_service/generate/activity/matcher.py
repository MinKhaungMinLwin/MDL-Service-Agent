"""CCPP guide schedule activity matching: build the query, select the activity, resolve anchor.

Combines lexical retrieval (activity.lexical.BM25Index) with optional semantic similarity
(activity.semantic.SemanticIndex) via reciprocal rank fusion, and exposes `resolve_activities`,
which returns one activity per input MDL row. Activity queries are rule-boosted so a document's
project phase (early design, delivery, commissioning, …) steers the BM25/RRF selection.
"""

from __future__ import annotations

from datetime import date, timedelta

from loguru import logger

from schedule_service.generate.activity.lexical import BM25Index
from schedule_service.generate.activity.models import Candidate, ScheduleActivity
from schedule_service.generate.activity.semantic import SemanticIndex
from schedule_service.generate.rule.models import ValidationRule
from schedule_service.normalizer import normalize_deliverable

_RRF_K = 60

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
    "transportation": "transportation delivery",
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


def build_activity_query(row: dict[str, str], rule: ValidationRule | None) -> str:
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


def resolve_activities(
    rows: list[dict[str, str]],
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    rules: list[ValidationRule | None],
    semantic_index: SemanticIndex | None,
) -> list[ScheduleActivity]:
    """Resolve the CCPP guide schedule activity for every row.

    Uses BM25 + semantic + RRF when a semantic index is supplied, else plain BM25 top-1.
    Either way the activity query is rule-boosted via build_activity_query.
    """
    if semantic_index is not None:
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
    bm25_scores = bm25.score(build_activity_query(row, rule))
    top_idx = max(range(len(bm25_scores)), key=lambda idx: bm25_scores[idx])
    return activities[top_idx]


def _match_activities_semantic(
    rows: list[dict[str, str]],
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    semantic_index: SemanticIndex,
    rules: list[ValidationRule | None],
) -> list[ScheduleActivity]:
    """Batch-embed activity queries and return the RRF top-1 activity for each row."""
    import numpy as np

    from common.embedding_client import AzureEmbeddingService
    from schedule_service.generate._shared.embedding_cache import embed_texts_cached

    activity_queries = [build_activity_query(row, rule) for row, rule in zip(rows, rules, strict=True)]
    unique_queries = list(dict.fromkeys(activity_queries))
    logger.info(
        "Semantic activity matching: embedding {} unique queries for {} rows",
        len(unique_queries), len(rows),
    )

    service = AzureEmbeddingService()
    raw_embeddings = embed_texts_cached(service, unique_queries)
    # One matmul: (n_unique, dims) → (n_unique, n_activities) cosine similarities.
    all_semantic_scores = semantic_index.score_matrix(np.array(raw_embeddings, dtype=np.float32))
    query_to_idx = {q: i for i, q in enumerate(unique_queries)}

    results: list[ScheduleActivity] = []
    for query in activity_queries:
        bm25_scores = bm25.score(query)
        semantic_scores = all_semantic_scores[query_to_idx[query]].tolist()
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


# --------------------------------------------------------------------------- RRF

def rank_desc(scores: list[float]) -> list[int]:
    """Return score indexes sorted descending."""
    return sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)


def rrf_candidates(
    activities: list[ScheduleActivity],
    bm25_scores: list[float],
    semantic_scores: list[float],
    retrieve_k: int,
    top_k: int,
    has_semantic: bool,
    rrf_k: int = _RRF_K,
) -> list[Candidate]:
    """Merge keyword and semantic ranks with reciprocal rank fusion."""
    bm25_order = rank_desc(bm25_scores)
    bm25_ranks = {index: rank for rank, index in enumerate(bm25_order, start=1)}
    semantic_order = rank_desc(semantic_scores) if has_semantic else []
    semantic_ranks = {index: rank for rank, index in enumerate(semantic_order, start=1)}

    candidate_indexes = set(bm25_order[:retrieve_k])
    if has_semantic:
        candidate_indexes.update(semantic_order[:retrieve_k])

    candidates: list[Candidate] = []
    for index in candidate_indexes:
        bm25_rank = bm25_ranks.get(index)
        semantic_rank = semantic_ranks.get(index)
        rrf_score = 0.0
        if bm25_rank is not None:
            rrf_score += 1.0 / (rrf_k + bm25_rank)
        if semantic_rank is not None:
            rrf_score += 1.0 / (rrf_k + semantic_rank)
        candidates.append(
            Candidate(
                activity=activities[index],
                bm25_rank=bm25_rank,
                semantic_rank=semantic_rank,
                bm25_score=bm25_scores[index],
                semantic_score=semantic_scores[index],
                rrf_score=rrf_score,
            )
        )

    candidates.sort(key=lambda item: item.rrf_score, reverse=True)
    return candidates[:top_k]


# ----------------------------------------------------------------------- anchor

def uses_finish_anchor(activity_keywords: list[str]) -> bool:
    """True if a rule's activity keywords indicate finish_date should anchor the VT formula."""
    return bool({k.lower() for k in activity_keywords} & _FINISH_DATE_KEYWORDS)


def resolve_anchor_date(
    start_date_str: str,
    finish_date_str: str,
    rule: ValidationRule,
    shift_days: int = 0,
) -> date | None:
    """Pick start_date or finish_date as anchor, then apply the NTP shift."""
    use_finish = uses_finish_anchor(rule.activity_keywords)
    date_str = finish_date_str if use_finish else start_date_str
    if not date_str:
        # Fallback to the other date when the preferred anchor is empty
        # (e.g. MPS "Issue" activities have no start_date but do have finish_date).
        date_str = start_date_str if use_finish else finish_date_str
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str) + timedelta(days=shift_days)
    except ValueError:
        return None
