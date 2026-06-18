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
from schedule_service.generate.activity.structured import StructuredActivityIndex
from schedule_service.generate.domain_mapping import DomainMapping, find_domain_mapping, load_domain_mappings
from schedule_service.generate.rule.models import ValidationRule
from schedule_service.normalizer import (
    canonical_deliverable_type,
    normalize_deliverable,
    refine_deliverable_with_title,
)

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
    # discipline_only: query and activity overlap only on a cross-cutting discipline
    # (electrical/HVAC) while the query's equipment system is NOT confirmed — a weak,
    # likely-wrong-system signal, ranked well below a real system match.
    "discipline_only": 0.5,
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
    ("bsedg", ("BSEDG", "BSDG", "BLACKSTART EMERGENCY DIESEL",
               "BLACKSTART DIESEL GENERATOR", "BLACKSTART GENERATOR")),
    # Closed Cooling Water — activities use abbreviated forms (CCWP/CCWS/CCW H/EX),
    # MDL docs use long forms. FIN FAN COOLER belongs to CCW H/EX in the CCPP schedule.
    ("ccw", ("CCW", "CCWP", "CCWS", "CCW H/EX",
             "CLOSED COOLING WATER", "CLOSED COOLING WATER SYSTEM",
             "CLOSED COOLING WATER PUMP", "FIN FAN COOLER", "FIN FAN")),
    ("cems", ("CEMS", "CONTINUOUS EMISSIONS MONITORING")),
    # Compressed/instrument/service air — activities use "(COMP Air ...)" / "(Purge Air System)";
    # MDL docs say "COMPRESSED AIR", "INSTRUMENT AIR", "AIR COMPRESSOR".
    ("compressed_air", ("COMPRESSED AIR", "INSTRUMENT AIR", "SERVICE AIR", "AIR COMPRESSOR",
                        "PLANT AIR", "PURGE AIR", "COMP AIR")),
    # Condensate (steam-cycle) — activities abbreviate to CEP / "(Condensate ...)".
    # Excludes bare "CONDENSER" on purpose: that collides with acc (Air Cooled CONDENSER).
    ("condensate", ("CONDENSATE", "CONDENSATE EXTRACTION", "CONDENSATE SYSTEM", "CEP")),
    # Crane & Hoist — activities say "(Crane & Hoist)" / "(Gantry Crane)";
    # MDL equipment says "CRANE", "HOIST", "JIB CRANE".
    ("crane_hoist", ("CRANE & HOIST", "CRANE AND HOIST", "GANTRY CRANE",
                     "CRANE", "HOIST", "JIB CRANE")),
    ("dc_ups", ("DC & UPS", "UPS", "DC SYSTEM", "125V DC", "220V DC",
                "DIRECT CURRENT", "UNINTERRUPTIBLE POWER SUPPLY")),
    ("dcs", ("DCS", "DISTRIBUTED CONTROL")),
    # Electrical — activities already include Earthing/Lighting/IPB; add MDL long forms.
    ("electrical", ("ELECTRICAL", "POWER METERING", "TARIFF METERING", "METERING SYSTEM",
                    "EARTHING", "EARTHING & LIGHTNING", "LIGHTNING PROTECTION", "GROUNDING",
                    "ISOLATED PHASE BUSDUCT", "IPB",
                    "LIGHTING & SMALL POWER", "SMALL POWER")),
    # Boiler/condensate feedwater — activities abbreviate to FWP/FWS/"FW PIPING"/BFP.
    ("feedwater", ("FEEDWATER", "FEED WATER", "BOILER FEED", "FWP", "FWS", "FW PIPING", "BFP")),
    ("fgp", ("FGP", "FUEL GAS", "GAS COMP", "GAS CONDITIONING")),
    # Fire fighting/protection — activities group these as "(... BLDG) ... Fire Fighting Sys."
    # / "Foam Station"; MDL docs cover alarm/detection/sprinkler/standpipe/clean-agent/etc.
    # Treated as a real system (not a cross-cutting discipline) because fire docs are
    # almost always dedicated; revisit _DISCIPLINE_SCOPES if cross-system bleed appears.
    ("fire_fighting", ("FIRE FIGHTING", "FIRE PROTECTION", "FIRE WATER", "FIRE SERVICE",
                       "FIRE ALARM", "FIRE DETECTION", "FIRE SUPPRESSION", "FIRE HYDRANT",
                       "SPRINKLER", "STANDPIPE", "STAND PIPE", "CLEAN AGENT", "WATER SPRAY",
                       "DELUGE", "HYDRANT", "FOAM STATION", "FOAM SYSTEM")),
    ("gtg", ("GTG", "GT", "GAS TURBINE", "GAS TURBINE GENERATOR")),
    ("gsut_uat", ("GSUT", "UAT", "UNIT AUXILIARY TRANSFORMER", "STEP UP", "TRANSFORMER")),
    ("h2", ("H2", "HYDROGEN")),
    ("hrsg", ("HRSG", "HEAT RECOVERY STEAM GENERATOR")),
    ("hvac", ("HVAC", "HEATING", "VENTILATING", "AIR CONDITIONING")),
    ("lab", ("LAB", "LABORATORY")),
    ("mv_lv", ("MV SWGR", "LV SWGR", "SWITCHGEAR", "MCC", "MOTOR CONTROL CENTER")),
    ("n2", ("N2", "NITROGEN")),
    ("reserve_boiler", ("RESERVE BOILER", "AUX BOILER", "AUXILIARY BOILER")),
    # Sampling — activities say "(Sampling System)" / "(Sampling Equip)";
    # no existing scope covered these 38 activities.
    ("sampling", ("SAMPLING SYSTEM", "SAMPLING EQUIP", "SAMPLING")),
    # Service/raw water — activities abbreviate service water to "(SWS)".
    ("service_water", ("SERVICE WATER", "RAW WATER", "SWS")),
    # Steam-cycle system (NOT the steam turbine) — all aliases are multiword to avoid
    # matching bare "STEAM" in "STEAM TURBINE"/"HEAT RECOVERY STEAM GENERATOR".
    ("steam", ("MAIN STEAM", "PROCESS STEAM", "HP STEAM", "IP STEAM", "LP STEAM",
               "AUXILIARY STEAM", "AUX STEAM", "STEAM DRAIN", "STEAM PIPING", "STEAM SYSTEM")),
    ("stg", ("STG", "ST", "STEAM TURBINE",
             "STEAM TURBINE GENERATOR", "STEAM TURBINE & GENERATOR")),
    # WTS — chemical dosing and DM/potable water systems are part of water treatment.
    ("wts", ("WTS", "WWTS", "WATER TREATMENT", "WASTE WATER", "EFFLUENT", "STP", "SEWAGE",
             "CHEMICAL DOSING", "CHEMICAL DOSING SYSTEM",
             "DM WATER", "DEMINERALIZED WATER", "POTABLE WATER")),
)

# Cross-cutting engineering disciplines, NOT equipment systems. Earthing, lighting,
# cable raceway, conduit, HVAC ducting etc. exist for every building and system, so an
# overlap on one of these alone does not confirm two documents share the same equipment.
# When a query carries a real equipment scope, a discipline-only overlap is treated as a
# weak `discipline_only` match (see `_scope_status`), not a full `match`.
_DISCIPLINE_SCOPES: frozenset[str] = frozenset({"electrical", "hvac"})

_GENERIC_ACTIVITY_NAMES = {
    "MECHANICAL DESIGN CRITERIA",
    "DESIGN CRITERIA",
}

_PHASE_BUCKETS: dict[str, tuple[str, ...]] = {
    "design_criteria": ("design_criteria", "system_design", "civil_design"),
    "design_drawing": ("system_design", "civil_design"),
    "system_design": ("system_design",),
    "civil_design": ("civil_design",),
    "procurement": ("procurement",),
    "commissioning": ("commissioning",),
    "manual": ("delivery", "procurement", "installation"),
    "delivery": ("delivery", "procurement"),
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
    equipment_agreement: bool = True
    generic_activity: bool = False
    bm25_rank: int | None = None
    semantic_rank: int | None = None
    bm25_score: float = 0.0
    semantic_score: float = 0.0
    rrf_score: float = 0.0
    adjusted_score: float = 0.0
    resolver_mode: str = "text"
    resolution_reason: str = ""
    structured_scope: str = ""
    structured_allowed_phases: str = ""
    structured_cell_size: int = 0

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
            "activity_match_equipment_agreement": "true" if self.equipment_agreement else "false",
            "activity_match_generic_activity": "true" if self.generic_activity else "false",
            "activity_match_bm25_rank": str(self.bm25_rank or ""),
            "activity_match_semantic_rank": str(self.semantic_rank or ""),
            "activity_match_bm25_score": _fmt_score(self.bm25_score),
            "activity_match_semantic_score": _fmt_score(self.semantic_score),
            "activity_match_rrf_score": _fmt_score(self.rrf_score),
            "activity_match_adjusted_score": _fmt_score(self.adjusted_score),
            "activity_match_resolver_mode": self.resolver_mode,
            "activity_match_resolution_reason": self.resolution_reason,
            "activity_match_structured_scope": self.structured_scope,
            "activity_match_structured_allowed_phases": self.structured_allowed_phases,
            "activity_match_structured_cell_size": str(self.structured_cell_size or ""),
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
    resolver_mode: str = "text",
    structured_index: StructuredActivityIndex | None = None,
) -> list[ScheduleActivity]:
    """Resolve the CCPP guide schedule activity for every row.

    Always uses BM25 + semantic + RRF for activity matching.
    The activity query is rule-boosted via build_activity_query.
    Deduplicates queries across rows to avoid re-scoring identical queries.
    """
    matched, _qualities = resolve_activity_matches(
        rows,
        activities,
        bm25,
        rules,
        semantic_index,
        resolver_mode=resolver_mode,
        structured_index=structured_index,
    )
    return matched


def resolve_activity_matches(
    rows: list[dict[str, str]],
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    rules: list[ValidationRule | None],
    semantic_index: SemanticIndex,
    resolver_mode: str = "text",
    structured_index: StructuredActivityIndex | None = None,
) -> tuple[list[ScheduleActivity], list[ActivityMatchQuality]]:
    """Resolve CCPP guide schedule activities and match-quality diagnostics."""
    return _match_activities_semantic(
        rows,
        activities,
        bm25,
        semantic_index,
        rules,
        resolver_mode=resolver_mode,
        structured_index=structured_index,
    )


def _match_activities_semantic(
    rows: list[dict[str, str]],
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    semantic_index: SemanticIndex,
    rules: list[ValidationRule | None],
    resolver_mode: str = "text",
    structured_index: StructuredActivityIndex | None = None,
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
    domain_mappings = load_domain_mappings() if resolver_mode in {"structured", "hybrid"} else []

    # Deduplicate BM25 scoring: score each unique query once
    query_bm25_scores = {q: bm25.score(q) for q in unique_queries}

    activity_phase_cache = [
        _activity_phase(" ".join([activity.activity_name_clean, activity.activity_name, activity.wbs_path]))
        for activity in activities
    ]

    results: list[ScheduleActivity] = []
    qualities: list[ActivityMatchQuality] = []
    for row, rule, query in zip(rows, rules, activity_queries, strict=True):
        query_phase = _query_phase(row, rule)
        bm25_scores = query_bm25_scores[query]
        semantic_scores = all_semantic_scores[query_to_idx[query]].tolist()
        allowed_indexes = _phase_bucket_indexes(query_phase, activity_phase_cache)
        candidates = rrf_candidates(
            activities=activities,
            bm25_scores=bm25_scores,
            semantic_scores=semantic_scores,
            retrieve_k=50,
            top_k=_RERANK_TOP_K,
            has_semantic=True,
            allowed_indexes=allowed_indexes,
        )
        candidate, quality = _select_activity_candidate_for_mode(
            row,
            rule,
            query,
            candidates,
            activities,
            bm25_scores,
            semantic_scores,
            resolver_mode=resolver_mode,
            structured_index=structured_index,
            domain_mappings=domain_mappings,
        )
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
    allowed_indexes: set[int] | None = None,
) -> list[Candidate]:
    """Merge keyword and semantic ranks with reciprocal rank fusion."""
    bm25_order = rank_desc(bm25_scores)
    bm25_ranks = {index: rank for rank, index in enumerate(bm25_order, start=1)}
    semantic_order = rank_desc(semantic_scores) if has_semantic else []
    semantic_ranks = {index: rank for rank, index in enumerate(semantic_order, start=1)}

    if allowed_indexes is not None:
        bm25_order = [index for index in bm25_order if index in allowed_indexes]
        semantic_order = [index for index in semantic_order if index in allowed_indexes]

    candidate_indexes = set(bm25_order[:retrieve_k])
    if has_semantic:
        candidate_indexes.update(semantic_order[:retrieve_k])

    if not candidate_indexes and allowed_indexes is not None:
        # Fall back to the unfiltered shortlist if the phase bucket is empty.
        bm25_order = rank_desc(bm25_scores)
        semantic_order = rank_desc(semantic_scores) if has_semantic else []
        bm25_ranks = {index: rank for rank, index in enumerate(bm25_order, start=1)}
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


def _select_activity_candidate_for_mode(
    row: dict[str, str],
    rule: ValidationRule | None,
    query: str,
    text_candidates: list[Candidate],
    activities: list[ScheduleActivity],
    bm25_scores: list[float],
    semantic_scores: list[float],
    *,
    resolver_mode: str,
    structured_index: StructuredActivityIndex | None,
    domain_mappings: list[DomainMapping],
) -> tuple[Candidate, ActivityMatchQuality]:
    if resolver_mode == "text":
        candidate, quality = _select_activity_candidate(row, rule, query, text_candidates)
        return candidate, replace(quality, resolver_mode="text", resolution_reason="text_rrf")

    structured_candidates, meta = _structured_candidates_for_row(
        row,
        rule,
        activities,
        bm25_scores,
        semantic_scores,
        structured_index=structured_index,
        domain_mappings=domain_mappings,
    )
    if structured_candidates:
        s_cand, s_qual = _select_activity_candidate(row, rule, query, structured_candidates)
        t_cand, t_qual = _select_activity_candidate(row, rule, query, text_candidates)
        # Don't prefer a structured result that would be blocked by the procurement-conflict
        # gate (design-phase doc mapped to a P.O activity via rule phase upgrade). In that
        # case, the text candidate — which filters by phase bucket — is the correct pick.
        s_procurement_conflict = (
            s_qual.query_phase in {"system_design", "design_drawing", "design_criteria", "civil_design"}
            and s_qual.activity_phase == "procurement"
        )
        if not s_procurement_conflict and s_qual.adjusted_score >= t_qual.adjusted_score * 1.05:
            return s_cand, replace(
                s_qual,
                resolver_mode="structured" if resolver_mode == "structured" else "hybrid",
                resolution_reason="structured_preferred",
                structured_scope="|".join(meta["effective_scope"]),
                structured_allowed_phases="|".join(meta["allowed_phases"]),
                structured_cell_size=len(structured_candidates),
            )
        reason = (
            "structured_blocked_procurement_conflict"
            if s_procurement_conflict
            else "structured_cell_found_text_preferred"
        )
        candidate, quality = t_cand, t_qual
        meta = {**meta, "reason": reason}
    else:
        candidate, quality = _select_activity_candidate(row, rule, query, text_candidates)

    if resolver_mode == "hybrid":
        return candidate, replace(
            quality,
            resolver_mode="hybrid",
            resolution_reason=meta["reason"],
            structured_scope="|".join(meta["effective_scope"]),
            structured_allowed_phases="|".join(meta["allowed_phases"]),
            structured_cell_size=0,
        )

    # Structured-only mode: keep the explanatory text candidate for output, but
    # force the gate to abstain when no (system, phase) cell exists.
    quality = replace(
        quality,
        resolver_mode="structured",
        resolution_reason=meta["reason"],
        structured_scope="|".join(meta["effective_scope"]),
        structured_allowed_phases="|".join(meta["allowed_phases"]),
        structured_cell_size=0,
        rrf_score=0.0,
        adjusted_score=0.0,
    )
    return candidate, quality


def _structured_candidates_for_row(
    row: dict[str, str],
    rule: ValidationRule | None,
    activities: list[ScheduleActivity],
    bm25_scores: list[float],
    semantic_scores: list[float],
    *,
    structured_index: StructuredActivityIndex | None,
    domain_mappings: list[DomainMapping],
) -> tuple[list[Candidate], dict[str, object]]:
    query_scope = list(resolve_doc_scope(row).keys)
    rule_scope = _rule_scope_keys(rule)
    effective_scope, _scope_source = _effective_query_scope(query_scope, rule_scope)
    query_phase = _query_phase(row, rule)
    allowed_phases = _structured_allowed_phases(row, effective_scope, query_phase, domain_mappings)
    meta = {
        "effective_scope": effective_scope,
        "allowed_phases": allowed_phases,
        "reason": "",
    }
    if structured_index is None:
        meta["reason"] = "structured_index_missing"
        return [], meta
    if not effective_scope:
        meta["reason"] = "structured_no_system"
        return [], meta
    if not allowed_phases:
        meta["reason"] = "structured_no_phase"
        return [], meta

    candidate_indexes = structured_index.indexes_for(effective_scope, allowed_phases)
    if candidate_indexes:
        return _candidates_from_indexes(candidate_indexes, activities, bm25_scores, semantic_scores), meta
    if any(scope in structured_index.systems for scope in effective_scope):
        meta["reason"] = "structured_phase_gap"
    else:
        meta["reason"] = "structured_system_absent"
    return [], meta


def _candidates_from_indexes(
    indexes: list[int],
    activities: list[ScheduleActivity],
    bm25_scores: list[float],
    semantic_scores: list[float],
    *,
    top_k: int = _RERANK_TOP_K,
) -> list[Candidate]:
    # Use within-cell ranks (not global ranks) so that activities in the correct
    # (system, phase) cell are not penalised for having a low global rank.
    # An activity at global rank 200 but cell rank 1 would score rrf≈0.004 globally
    # (failing the 0.02 gate) yet rrf≈0.033 locally — correctly passing the gate.
    # bm25_score / semantic_score remain global similarity values for transparency.
    local_bm25_order = sorted(indexes, key=lambda i: bm25_scores[i], reverse=True)
    local_bm25_ranks = {idx: rank for rank, idx in enumerate(local_bm25_order, start=1)}
    local_semantic_order = sorted(indexes, key=lambda i: semantic_scores[i], reverse=True)
    local_semantic_ranks = {idx: rank for rank, idx in enumerate(local_semantic_order, start=1)}
    candidates: list[Candidate] = []
    for index in indexes:
        bm25_rank = local_bm25_ranks.get(index)
        semantic_rank = local_semantic_ranks.get(index)
        rrf_score = 0.0
        if bm25_rank is not None:
            rrf_score += 1.0 / (_RRF_K + bm25_rank)
        if semantic_rank is not None:
            rrf_score += 1.0 / (_RRF_K + semantic_rank)
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
    query_scope = list(resolve_doc_scope(row).keys)
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
        equipment_agreement=equipment_agreement(
            row.get("Equipment", ""),
            row.get("Title", ""),
            f"{activity.activity_name_clean} {activity.activity_name}",
            activity_scope,
        ),
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
    scope_text = " ".join([row.get("Equipment", ""), row.get("System", ""), row.get("Building", "")]).upper()
    text = f"{deliverable} {title}"
    if "DESIGN CRITERIA" in text:
        return "design_criteria"
    if any(term in text for term in ("P&ID", "P&I", "SYSTEM DESCRIPTION", "CONFIGURATION", "LOGIC")):
        return "system_design"
    if any(term in text for term in ("HAZARDOUS AREA CLASSIFICATION", "CLASSIFICATION")):
        return "system_design"
    if any(term in text for term in ("TECHNICAL SPECIFICATION", "SPECIFICATION", "DATA SHEET", "DATASHEET", "CURVE")):
        return "procurement"
    if any(term in text for term in ("FOUNDATION", "DESIGN REPORT", "CALCULATION")):
        return "civil_design"
    if study_or_report_phase := _study_report_phase(text, scope_text):
        return study_or_report_phase
    if any(term in text for term in ("SITE PLAN", "PLOT PLAN")):
        return "civil_design"
    if drawing_phase := _design_drawing_phase(text, scope_text):
        return drawing_phase
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


def _structured_allowed_phases(
    row: dict[str, str],
    effective_scope: list[str],
    query_phase: str,
    domain_mappings: list[DomainMapping],
) -> list[str]:
    deliverable = row.get("Deliverable", "").strip()
    title = row.get("Title", "").strip()
    family, subtype = canonical_deliverable_type(
        deliverable=refine_deliverable_with_title(deliverable, title),
        title=title,
    )
    mapping_keys = [key for key in [_deliverable_mapping_key(family, subtype)] if key]
    mapping_keys.append(family)
    scope_families = list(effective_scope) if effective_scope else ["*"]
    scope_families.append("*")

    phases: list[str] = []
    for mapping_key in mapping_keys:
        for scope_family in scope_families:
            mapping = find_domain_mapping(mapping_key, scope_family, domain_mappings)
            if mapping and mapping.allowed_activity_phases:
                phases.extend(mapping.allowed_activity_phases)
                break
        if phases:
            break

    if not phases and query_phase:
        phases.extend(_PHASE_BUCKETS.get(query_phase, ()))
        if not phases:
            phases.append(query_phase)
    return list(dict.fromkeys(phase for phase in phases if phase))


def _deliverable_mapping_key(family: str, subtype: str) -> str:
    if subtype == "p_id":
        return "p&id"
    if subtype == "technical_specification":
        return "technical_specification"
    if subtype == "system_description":
        return "system_description"
    if family in {"diagram", "classification", "curve"}:
        return family
    return ""


def _study_report_phase(text: str, scope_text: str) -> str:
    """Infer phase for classification/study/report rows before rule keyword boost."""
    engineering_terms = (
        "HAZOP",
        "SIL",
        "OPERABILITY",
        "HARMONIC",
        "SHORT CIRCUIT",
        "LOAD FLOW",
        "PROTECTION RELAY",
        "PHILOSOPHY",
        "ANALYSIS",
        "CFD",
        "PERFORMANCE",
        "PROCESS",
        "SYSTEM",
    )
    civil_terms = (
        "FOUNDATION",
        "FDN",
        "STRUCTURE",
        "BUILDING",
        "SHELTER",
        "PIPE RACK",
        "PLOT PLAN",
        "SITE PLAN",
        "ARCHITECTURAL",
        "CIVIL",
    )
    if not any(term in text for term in ("STUDY", "REPORT", "CLASSIFICATION")):
        return ""
    if any(term in text or term in scope_text for term in civil_terms):
        return "civil_design"
    if any(term in text or term in scope_text for term in engineering_terms):
        return "system_design"
    return ""


def _design_drawing_phase(text: str, scope_text: str) -> str:
    """Infer whether a drawing-like document belongs to system or civil design."""
    if not any(term in text for term in ("LAYOUT", "ARRANGEMENT", "OUTLINE", "DRAWING", "DIAGRAM")):
        return ""

    civil_terms = (
        "FOUNDATION",
        "FDN",
        "STRUCTURE",
        "BUILDING",
        "SHELTER",
        "PIPE RACK",
        "PLOT PLAN",
        "SITE PLAN",
        "ELEVATION",
        "SECTION",
        "REBAR",
        "EMBEDDED",
        "ARCHITECTURAL",
        "CIVIL",
    )
    system_terms = (
        "P&ID",
        "P&I",
        "FLOW DIAGRAM",
        "CONTROL LOOP",
        "CONTROL LOGIC",
        "WIRING",
        "ELEMENTARY",
        "SINGLE LINE",
        "ISOMETRIC",
        "I/O",
        "OUTLINE DRAWING",
        "GENERAL ARRANGEMENT DRAWING FOR",
        "ARRANGEMENT DRAWING FOR",
    )
    if any(term in text or term in scope_text for term in civil_terms):
        return "civil_design"
    if any(term in text or term in scope_text for term in system_terms):
        return "system_design"
    if "GENERAL ARRANGEMENT" in text and scope_text.strip():
        return "system_design"
    return ""


def _phase_bucket_indexes(query_phase: str, activity_phases: list[str]) -> set[int] | None:
    """Return activity indexes allowed for a query phase, or None for no filter."""
    allowed_phases = set(_PHASE_BUCKETS.get(query_phase, ()))
    if not allowed_phases:
        return None
    allowed_indexes = {
        index for index, activity_phase in enumerate(activity_phases)
        if activity_phase in allowed_phases
    }
    # Keep unknowns only as a fallback via rrf_candidates; do not include them here.
    return allowed_indexes or None


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


_COMPATIBLE_PHASE_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("design_drawing", "system_design"),
    ("design_drawing", "civil_design"),
    ("manual", "delivery"),
    ("manual", "procurement"),
    # O&M manuals are submitted after installation is complete.
    ("manual", "installation"),
    # Design criteria documents inform both system and civil design activities.
    ("design_criteria", "system_design"),
    ("design_criteria", "civil_design"),
})


def _phase_status(query_phase: str, activity_phase: str, rule: ValidationRule | None = None) -> str:
    if not query_phase:
        return "query_unknown"
    if not activity_phase:
        return "activity_unknown"
    if query_phase == activity_phase:
        return "match"
    # A rule's activity_keywords can confirm the activity phase (upgrade to match),
    # but must NOT override the compatible-pair check — doing so was causing
    # design_drawing→civil_design and design_drawing→system_design to be reported as
    # "mismatch" whenever a rule happened to have P.O/delivery keywords, blocking
    # 155 rows that are actually valid matches.
    rule_phase = _activity_keyword_phase(rule.activity_keywords) if rule else ""
    if rule_phase == activity_phase:
        return "match"
    return "compatible" if (query_phase, activity_phase) in _COMPATIBLE_PHASE_PAIRS else "mismatch"


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


# Equipment/title tokens too generic to corroborate an activity match on their own.
_GENERIC_AGREEMENT_TOKENS: frozenset[str] = frozenset({
    "system", "design", "drawing", "data", "calculation", "calculations", "list",
    "report", "manual", "specification", "diagram", "plan", "layout", "arrangement",
    "detail", "details", "sheet", "general", "equip", "equipment", "technical",
    "load", "civil", "structure", "structural", "outline", "elevation", "section",
    "schedule", "study", "vendor", "package", "area", "shelter", "building", "bldg",
})

# Sibling scope keys that denote the same physical system, so a document tagged one
# and an activity tagged the other still agree. Air Cooled Condenser IS the condensate
# sink, so acc/condensate are interchangeable for agreement purposes.
_SCOPE_COMPAT: tuple[frozenset[str], ...] = (
    frozenset({"acc", "condensate"}),
)


def _scopes_compatible(doc_scope: set[str], activity_scope: set[str]) -> bool:
    return any(
        (doc_scope & group) and (activity_scope & group) for group in _SCOPE_COMPAT
    )


def _agreement_tokens(text: str) -> set[str]:
    import re

    return {
        t
        for t in re.findall(r"[a-z0-9]+", text.lower())
        if len(t) >= 4 and t not in _GENERIC_AGREEMENT_TOKENS
    }


def equipment_agreement(
    equipment: str, title: str, activity_name: str, activity_scope: list[str]
) -> bool:
    """True when the chosen activity is corroborated by the document's own equipment/title.

    Guards against false scope ``match``es that arise only from the (sometimes
    misclassified) System field or the rule's scope — e.g. a duct-burner water-spray
    calc landing on a Chemical Dosing building because both carry the broad ``wts``
    bucket, or an ammonia tank landing on a compressed-air receiver-tank shelter.

    Agreement holds if any of:
      A. the activity scope overlaps the scope derived from equipment+title (NOT System);
      B. the doc and activity scopes are compatible siblings (acc/condensate);
      C. a concrete (non-generic) equipment/title token literally names the activity.
    When the activity carries no scope at all there is nothing to contradict, so the
    decision is left to the existing unscoped/phase gates (returns True).
    """
    act = set(activity_scope)
    if not act:
        return True
    doc_scope = set(_scope_keys(f"{equipment} {title}"))
    if doc_scope & act:
        return True
    if _scopes_compatible(doc_scope, act):
        return True
    return bool(_agreement_tokens(f"{equipment} {title}") & _agreement_tokens(activity_name))


def _scope_status(query_scope: list[str], activity_scope: list[str]) -> str:
    if not query_scope:
        return "query_unscoped"
    if not activity_scope:
        return "activity_unscoped"
    q = set(query_scope)
    a = set(activity_scope)
    overlap = q & a
    if not overlap:
        return "mismatch"
    q_systems = q - _DISCIPLINE_SCOPES
    if q_systems:
        # The query names a real equipment system: a confident match must agree on that
        # system. Overlapping only on a cross-cutting discipline (electrical/HVAC) is a
        # weak signal — the document's equipment is left unconfirmed.
        if q_systems & a:
            return "match"
        return "discipline_only"
    # The query is purely a discipline scope (e.g. plant-wide "HVAC SYSTEM" document):
    # a discipline overlap is the strongest signal available and is a legitimate match.
    return "match"


def _rule_scope_keys(rule: ValidationRule | None) -> list[str]:
    if rule is None:
        return []
    text = " ".join(part for part in [rule.item_name, rule.doc_keyword] if part)
    return _scope_keys(text)


@dataclass(frozen=True)
class DocScope:
    """Document scope merged from structured fields with Title/Others fallback."""

    keys: tuple[str, ...]
    origin: str  # "esb" | "title" | "others" | "esb+title" | "none"
    conflict: bool  # structured (E/S/B) scope and Title scope both exist but disagree


def resolve_doc_scope(row: dict[str, str]) -> DocScope:
    """Merge document scope from Equipment/System/Building, then Title, then Others.

    Policy (see scope_source_analysis memory):
      * Structured fields (E/S/B) are the primary, most-trusted source.
      * When they yield no scope, fall back to Title, then Others — this recovers the
        ~28% of documents that carry their scope only in the title (e.g. "STEAM DRAIN
        & FGP DEMIN SUPPLY").
      * When E/S/B and Title both yield scope but are disjoint, keep BOTH as candidates
        and flag a conflict, so the activity search can pick whichever system its best
        match actually belongs to instead of being forced onto a possibly-misclassified
        structured field (e.g. a FIRE ALARM document tagged System=WASTE WATER).
    """
    esb = set(_scope_keys(" ".join([
        row.get("Equipment", ""), row.get("System", ""), row.get("Building", ""),
    ])))
    title = set(_scope_keys(row.get("Title", "")))
    others = set(_scope_keys(row.get("Others", "")))

    if esb:
        if title and not (esb & title):
            return DocScope(tuple(sorted(esb | title)), "esb+title", True)
        return DocScope(tuple(sorted(esb)), "esb", False)
    if title:
        return DocScope(tuple(sorted(title)), "title", False)
    if others:
        return DocScope(tuple(sorted(others)), "others", False)
    return DocScope((), "none", False)


def _effective_query_scope(query_scope: list[str], rule_scope: list[str]) -> tuple[list[str], str]:
    # The document's own classified scope (Equipment / System / Building / Title) is the
    # ground truth about what the document is. The matched validation rule is often a
    # generic deliverable rule whose incidental equipment (from its Item column) is
    # unrelated to this document; trusting it over the document's own scope hijacks the
    # activity search to the wrong system and makes scope_status self-confirming. So the
    # query scope wins whenever it exists; the rule scope is only a fallback for documents
    # that carry no scope of their own.
    if query_scope:
        return query_scope, "query"
    if rule_scope:
        return rule_scope, "rule"
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
