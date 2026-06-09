"""CCPP guide schedule activity matching: build the query, select the activity, resolve anchor.

Combines lexical retrieval (activity.lexical.BM25Index) with semantic similarity
(activity.semantic.SemanticIndex) via reciprocal rank fusion, and exposes `resolve_activities`,
which returns one activity per input MDL row. Semantic matching is mandatory. Activity queries
are rule-boosted so a document's project phase (early design, delivery, commissioning, …)
steers the BM25/RRF selection.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from loguru import logger

from schedule_service.generate.activity.lexical import BM25Index
from schedule_service.generate.activity.models import Candidate, ScheduleActivity
from schedule_service.generate.activity.semantic import SemanticIndex
from schedule_service.generate.rule.models import ValidationRule
from schedule_service.normalizer import normalize_deliverable, refine_deliverable_with_title

_RRF_K = 60
_RERANK_TOP_K = 10

_PHASE_MULTIPLIER: dict[str, float] = {
    "match": 1.0,
    "compatible": 0.75,
    "query_unknown": 0.75,
    "activity_unknown": 0.75,
    "mismatch": 0.25,
}
_SCOPE_MULTIPLIER: dict[str, float] = {
    "match": 1.0,
    "query_unscoped": 0.75,
    "activity_unscoped": 0.75,
    "mismatch": 0.25,
    "rule_scope_only": 0.85,
}
_GENERIC_ACTIVITY_MULTIPLIER = 0.8

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

_SCOPE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("acc", ("ACC", "AIR COOLED CONDENSER", "COND AIR EXT")),
    ("bop", ("BOP", "BALANCE OF PLANT")),
    ("bsedg", ("BSEDG", "BSDG", "BLACKSTART EMERGENCY DIESEL")),
    ("cems", ("CEMS", "CONTINUOUS EMISSIONS MONITORING")),
    ("dc_ups", ("DC & UPS", "UPS", "DC SYSTEM", "125V DC", "220V DC")),
    ("dcs", ("DCS", "DISTRIBUTED CONTROL")),
    ("electrical", ("ELECTRICAL", "POWER METERING", "TARIFF METERING", "METERING SYSTEM")),
    ("fgp", ("FGP", "FUEL GAS", "GAS COMP", "GAS CONDITIONING")),
    ("gtg", ("GTG", "GT", "GAS TURBINE")),
    ("gsut_uat", ("GSUT", "UAT", "UNIT AUXILIARY TRANSFORMER", "STEP UP", "TRANSFORMER")),
    ("h2", ("H2", "HYDROGEN")),
    ("hrsg", ("HRSG", "HEAT RECOVERY STEAM GENERATOR")),
    ("hvac", ("HVAC", "HEATING", "VENTILATING", "AIR CONDITIONING")),
    ("lab", ("LAB", "LABORATORY")),
    ("mv_lv", ("MV SWGR", "LV SWGR", "SWITCHGEAR", "MCC", "MOTOR CONTROL CENTER")),
    ("n2", ("N2", "NITROGEN")),
    ("reserve_boiler", ("RESERVE BOILER", "AUX BOILER", "AUXILIARY BOILER")),
    ("stg", ("STG", "ST", "STEAM TURBINE")),
    ("wts", ("WTS", "WWTS", "WATER TREATMENT", "WASTE WATER", "EFFLUENT", "STP", "SEWAGE")),
)

_GENERIC_ACTIVITY_NAMES = {
    "MECHANICAL DESIGN CRITERIA",
    "DESIGN CRITERIA",
}


@dataclass(frozen=True)
class ActivityMatchQuality:
    """Diagnostics for one CCPP activity match decision."""

    query: str
    query_phase: str = ""
    activity_phase: str = ""
    phase_status: str = ""
    query_scope: str = ""
    rule_scope: str = ""
    effective_scope: str = ""
    scope_source: str = ""
    activity_scope: str = ""
    scope_status: str = ""
    generic_activity: bool = False
    bm25_rank: int | None = None
    semantic_rank: int | None = None
    bm25_score: float = 0.0
    semantic_score: float = 0.0
    rrf_score: float = 0.0
    adjusted_score: float = 0.0

    def output_fields(self) -> dict[str, str]:
        """Return stable string fields for generated schedule outputs."""
        return {
            "activity_match_query_phase": self.query_phase,
            "activity_match_activity_phase": self.activity_phase,
            "activity_match_phase_status": self.phase_status,
            "activity_match_query_scope": self.query_scope,
            "activity_match_rule_scope": self.rule_scope,
            "activity_match_effective_scope": self.effective_scope,
            "activity_match_scope_source": self.scope_source,
            "activity_match_activity_scope": self.activity_scope,
            "activity_match_scope_status": self.scope_status,
            "activity_match_generic_activity": "true" if self.generic_activity else "false",
            "activity_match_bm25_rank": str(self.bm25_rank or ""),
            "activity_match_semantic_rank": str(self.semantic_rank or ""),
            "activity_match_bm25_score": _fmt_score(self.bm25_score),
            "activity_match_semantic_score": _fmt_score(self.semantic_score),
            "activity_match_rrf_score": _fmt_score(self.rrf_score),
            "activity_match_adjusted_score": _fmt_score(self.adjusted_score),
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
    semantic_index: SemanticIndex,
) -> list[ScheduleActivity]:
    """Resolve the CCPP guide schedule activity for every row.

    Always uses BM25 + semantic + RRF for activity matching.
    The activity query is rule-boosted via build_activity_query.
    Deduplicates queries across rows to avoid re-scoring identical queries.
    """
    matched, _qualities = resolve_activity_matches(rows, activities, bm25, rules, semantic_index)
    return matched


def resolve_activity_matches(
    rows: list[dict[str, str]],
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    rules: list[ValidationRule | None],
    semantic_index: SemanticIndex,
) -> tuple[list[ScheduleActivity], list[ActivityMatchQuality]]:
    """Resolve CCPP guide schedule activities and match-quality diagnostics."""
    return _match_activities_semantic(rows, activities, bm25, semantic_index, rules)


def _match_activities_semantic(
    rows: list[dict[str, str]],
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    semantic_index: SemanticIndex,
    rules: list[ValidationRule | None],
) -> tuple[list[ScheduleActivity], list[ActivityMatchQuality]]:
    """Batch-embed activity queries and return the quality-reranked activity for each row.

    Deduplicates both embedding and BM25 scoring to avoid redundant computation.
    """
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

    # Deduplicate BM25 scoring: score each unique query once
    query_bm25_scores = {q: bm25.score(q) for q in unique_queries}

    results: list[ScheduleActivity] = []
    qualities: list[ActivityMatchQuality] = []
    for row, rule, query in zip(rows, rules, activity_queries, strict=True):
        bm25_scores = query_bm25_scores[query]
        semantic_scores = all_semantic_scores[query_to_idx[query]].tolist()
        candidates = rrf_candidates(
            activities=activities,
            bm25_scores=bm25_scores,
            semantic_scores=semantic_scores,
            retrieve_k=50,
            top_k=_RERANK_TOP_K,
            has_semantic=True,
        )
        candidate, quality = _select_activity_candidate(row, rule, query, candidates)
        results.append(candidate.activity)
        qualities.append(quality)
    return results, qualities


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


# ---------------------------------------------------------------------- quality

def _select_activity_candidate(
    row: dict[str, str],
    rule: ValidationRule | None,
    query: str,
    candidates: list[Candidate],
) -> tuple[Candidate, ActivityMatchQuality]:
    """Select the best activity by applying phase/scope quality to the RRF shortlist."""
    if not candidates:
        raise ValueError("Activity reranking requires at least one candidate")

    scored: list[tuple[float, float, int, Candidate, ActivityMatchQuality]] = []
    for index, candidate in enumerate(candidates):
        quality = _activity_quality(row, rule, query, candidate)
        adjusted_score = _activity_adjusted_score(quality)
        quality = replace(quality, adjusted_score=adjusted_score)
        scored.append((adjusted_score, candidate.rrf_score, -index, candidate, quality))

    scoped = [item for item in scored if item[4].scope_status == "match"]
    if scoped:
        scored = scoped
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    _adjusted_score, _rrf_score, _rank_tiebreak, candidate, quality = scored[0]
    return candidate, quality


def _activity_adjusted_score(quality: ActivityMatchQuality) -> float:
    """Return RRF adjusted by phase/scope diagnostics and generic-activity penalty."""
    score = quality.rrf_score
    score *= _PHASE_MULTIPLIER.get(quality.phase_status, 0.75)
    score *= _SCOPE_MULTIPLIER.get(quality.scope_status, 0.75)
    if quality.generic_activity:
        score *= _GENERIC_ACTIVITY_MULTIPLIER
    if quality.scope_source == "rule" and quality.scope_status != "match":
        score *= 0.5
    return score

def _activity_quality(
    row: dict[str, str],
    rule: ValidationRule | None,
    query: str,
    candidate: Candidate,
) -> ActivityMatchQuality:
    activity = candidate.activity
    activity_text = " ".join([activity.activity_name_clean, activity.activity_name, activity.wbs_path])
    query_phase = _query_phase(row, rule)
    activity_phase = _activity_phase(activity_text)
    query_scope = _scope_keys(" ".join([row.get("Equipment", ""), row.get("System", ""), row.get("Building", "")]))
    rule_scope = _rule_scope_keys(rule)
    effective_scope, scope_source = _effective_query_scope(query_scope, rule_scope)
    activity_scope = _scope_keys(activity_text)
    return ActivityMatchQuality(
        query=query,
        query_phase=query_phase,
        activity_phase=activity_phase,
        phase_status=_phase_status(query_phase, activity_phase, rule),
        query_scope="|".join(query_scope),
        rule_scope="|".join(rule_scope),
        effective_scope="|".join(effective_scope),
        scope_source=scope_source,
        activity_scope="|".join(activity_scope),
        scope_status=_scope_status(effective_scope, activity_scope),
        generic_activity=_is_generic_activity(activity),
        bm25_rank=candidate.bm25_rank,
        semantic_rank=candidate.semantic_rank,
        bm25_score=candidate.bm25_score,
        semantic_score=candidate.semantic_score,
        rrf_score=candidate.rrf_score,
    )


def _query_phase(row: dict[str, str], rule: ValidationRule | None) -> str:
    title = row.get("Title", "").upper()
    deliverable = normalize_deliverable(
        refine_deliverable_with_title(row.get("Deliverable", "").strip(), title)
    ).upper()
    text = f"{deliverable} {title}"
    if "DESIGN CRITERIA" in text:
        return "design_criteria"
    if any(term in text for term in ("P&ID", "P&I", "SYSTEM DESCRIPTION", "CONFIGURATION", "LOGIC")):
        return "system_design"
    if any(term in text for term in ("TECHNICAL SPECIFICATION", "SPECIFICATION", "DATA SHEET", "DATASHEET", "CURVE")):
        return "procurement"
    if any(term in text for term in ("FOUNDATION", "DESIGN REPORT", "CALCULATION")):
        return "civil_design"
    if any(term in text for term in ("COMMISSIONING", "TEST")):
        return "commissioning"
    if any(term in text for term in ("MANUAL", "O&M", "OPERATION & MAINTENANCE", "OPERATION AND MAINTENANCE")):
        return "manual"
    if any(term in text for term in ("TERMINAL POINT LIST", "LOAD LIST", "I/O LIST", "SIGNAL LIST", "CABLE LIST")):
        return "procurement"
    if any(term in text for term in ("LAYOUT", "ARRANGEMENT", "OUTLINE", "DRAWING", "DIAGRAM")):
        return "design_drawing"
    if rule:
        boosted = _activity_keyword_phase(rule.activity_keywords)
        if boosted:
            return boosted
    return ""


def _activity_keyword_phase(activity_keywords: list[str]) -> str:
    keys = {kw.lower().strip() for kw in activity_keywords}
    if keys & {"delivery", "fob", "transportation", "fo b"}:
        return "delivery"
    if keys & {"p.o", "po", "pof", "manufacturing"}:
        return "procurement"
    if "commissioning" in keys:
        return "commissioning"
    return ""


def _activity_phase(text: str) -> str:
    value = text.upper()
    if "DESIGN CRITERIA" in value:
        return "design_criteria"
    if any(term in value for term in ("P&ID", "P&I", "SYSTEM DESIGN", "PROCESS", "CONFIGURATION", "LOGIC")):
        return "system_design"
    if any(term in value for term in ("TRANSPORTATION", "DELIVERY", "FOB")):
        return "delivery"
    if any(term in value for term in ("COMMISSIONING", "HYDRO TEST", "PERFORMANCE TEST", "TEST")):
        return "commissioning"
    if any(term in value for term in ("FDN", "FOUNDATION", "CIVIL", "STRUCTURE DESIGN", "SHELTER DESIGN")):
        return "civil_design"
    if any(term in value for term in ("P.O", "PROCUREMENT", "KEY DATA", "MPS", "VENDOR")):
        return "procurement"
    if any(term in value for term in ("INSTALLATION", "ERECTION")):
        return "installation"
    return ""


def _phase_status(query_phase: str, activity_phase: str, rule: ValidationRule | None = None) -> str:
    if not query_phase:
        return "query_unknown"
    if not activity_phase:
        return "activity_unknown"
    if query_phase == activity_phase:
        return "match"
    rule_phase = _activity_keyword_phase(rule.activity_keywords) if rule else ""
    if rule_phase:
        return "match" if rule_phase == activity_phase else "mismatch"
    compatible = {
        ("design_drawing", "system_design"),
        ("design_drawing", "civil_design"),
        ("manual", "delivery"),
        ("manual", "procurement"),
    }
    return "compatible" if (query_phase, activity_phase) in compatible else "mismatch"


def _scope_keys(text: str) -> list[str]:
    value = f" {text.upper()} "
    keys = []
    for key, aliases in _SCOPE_ALIASES:
        if any(_contains_scope_alias(value, alias) for alias in aliases):
            keys.append(key)
    return sorted(set(keys))


def _contains_scope_alias(value: str, alias: str) -> bool:
    import re

    cleaned = alias.strip().upper()
    if not cleaned:
        return False
    return bool(re.search(rf"(?<![A-Z0-9]){re.escape(cleaned)}(?![A-Z0-9])", value))


def _scope_status(query_scope: list[str], activity_scope: list[str]) -> str:
    if not query_scope:
        return "query_unscoped"
    if not activity_scope:
        return "activity_unscoped"
    return "match" if set(query_scope).intersection(activity_scope) else "mismatch"


def _rule_scope_keys(rule: ValidationRule | None) -> list[str]:
    if rule is None:
        return []
    text = " ".join(part for part in [rule.item_name, rule.doc_keyword] if part)
    return _scope_keys(text)


def _effective_query_scope(query_scope: list[str], rule_scope: list[str]) -> tuple[list[str], str]:
    if rule_scope:
        return rule_scope, "rule"
    if query_scope:
        return query_scope, "query"
    return [], ""


def _is_generic_activity(activity: ScheduleActivity) -> bool:
    name = (activity.activity_name_clean or activity.activity_name).upper().strip()
    if name in _GENERIC_ACTIVITY_NAMES:
        return True
    text = f"{activity.activity_name_clean} {activity.activity_name} {activity.wbs_path}".upper()
    return not _scope_keys(text)


def _fmt_score(value: float) -> str:
    return f"{value:.4f}" if value else ""


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
