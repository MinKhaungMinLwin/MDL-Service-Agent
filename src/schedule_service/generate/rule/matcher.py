"""Validation-rule matching: build the query, then select the best rule.

Combines lexical retrieval (rule.lexical.RuleLexicalIndex) with semantic similarity
(rule.semantic.RuleSemanticIndex) into a single hybrid score, and exposes one entry
point, `resolve_rules`, that returns one rule (or None) per input MDL row. Semantic
matching is mandatory — there is no token-only path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger

from schedule_service.generate.rule.lexical import RuleLexicalIndex
from schedule_service.generate.rule.models import ValidationRule
from schedule_service.generate.rule.semantic import RuleSemanticIndex
from schedule_service.normalizer import (
    canonical_deliverable_type,
    equipment_to_abbr,
    normalize_deliverable,
    refine_deliverable_with_title,
)

# Priority multiplier applied to hybrid scores so specific rules (priority 1)
# beat generic rules (priority 3) even when semantic similarity is slightly higher.
_PRIORITY_WEIGHT: dict[int, float] = {1: 1.0, 2: 0.85, 3: 0.70}
_MAX_RULE_CANDIDATES = 300

_SCOPE_TOKENS = {
    "acc",
    "bfp",
    "bop",
    "bsedg",
    "ccwp",
    "cep",
    "dcs",
    "fgp",
    "gt",
    "gtg",
    "hrsg",
    "st",
    "stg",
}

_SCOPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("acc", ("ACC", "AIR COOLED CONDENSER", "COND AIR EXT")),
    ("hrsg", ("HRSG", "HEAT RECOVERY STEAM GENERATOR")),
    ("gtg", ("GTG", "GT ", "GAS TURBINE GENERATOR", "GAS TURBINE")),
    ("stg", ("STG", "ST ", "STEAM TURBINE GENERATOR", "STEAM TURBINE")),
    ("dcs", ("DCS", "DISTRIBUTED CONTROL SYSTEM")),
    ("cems", ("CEMS", "CONTINUOUS EMISSION MONITORING")),
    ("wts", ("WATER TREATMENT", "WTS")),
    ("reserve_boiler", ("RESERVE BOILER", "AUX BOILER", "AUXILIARY BOILER")),
    ("bop", ("BOP", "BALANCE OF PLANT")),
    ("fgp", ("FGP", "FUEL GAS PACKAGE", "FUEL GAS")),
)

_DELIVERABLE_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("painting_specification", ("PAINTING SPECIFICATION", "PAINT SPECIFICATION")),
    ("painting", ("PAINTING", "PAINT")),
    ("foundation", ("FOUNDATION", "FDN")),
    ("p&id", ("P&ID", "P&I", "PIPING INSTRUMENT", "PIPING & INSTRUMENT")),
    ("technical_specification", ("TECHNICAL SPECIFICATION", "TECHNICAL SPECIFICATIONS", "SPECIFICATION")),
    ("datasheet", ("DATASHEET", "DATA SHEET")),
    ("system_description", ("SYSTEM DESCRIPTION", "DESCRIPTION")),
    ("design_criteria", ("DESIGN CRITERIA", "CRITERIA")),
    ("design_report", ("DESIGN REPORT", "REPORT")),
    ("design_recommendation", ("DESIGN RECOMMENDATION", "DESIGN RECOMMENDATIONS", "RECOMMENDATION")),
    ("arrangement", ("GENERAL ARRANGEMENT", "ARRANGEMENT", "ARRG")),
    ("outline", ("OUTLINE",)),
    ("procedure", ("PROCEDURE",)),
    ("manual", ("MANUAL", "O&M", "OPERATION AND MAINTENANCE")),
    ("calculation", ("CALCULATION", "CALC")),
    ("study", ("STUDY",)),
    ("curve", ("CURVE", "CURVES", "PERFORMANCE DATA", "CAPABILITY")),
    ("classification", ("CLASSIFICATION",)),
    ("diagram", ("DIAGRAM", "SCHEMATIC", "SINGLE LINE")),
    ("configuration", ("CONFIGURATION",)),
    ("list", ("LIST",)),
    ("logic", ("LOGIC",)),
)

_STRICT_FAMILY_MATCH = {
    "classification",
    "curve",
    "design_recommendation",
    "painting_specification",
    "foundation",
    "diagram",
    "procedure",
    "study",
}

_GENERIC_SUBTYPES = {
    "",
    "calculation",
    "data_sheet",
    "diagram",
    "drawing",
    "list",
    "manual",
    "procedure",
    "report",
    "specification",
    "technical_specification",
}

_GENERIC_RULE_TOKENS = {
    "andid",
    "accessories",
    "and",
    "arrangement",
    "calculation",
    "curve",
    "data",
    "datasheet",
    "description",
    "diagram",
    "document",
    "documents",
    "drawing",
    "for",
    "general",
    "list",
    "manual",
    "of",
    "p",
    "p&id",
    "plan",
    "procedure",
    "report",
    "specification",
    "system",
    "technical",
}

_SUBTYPE_LABELS = {
    "cfd_report": "CFD Report",
    "control_logic_diagram": "Control Logic Diagram",
    "control_loop_diagram": "Control Loop Diagram",
    "design_report": "Design Report",
    "drain_pump_specification": "Drain Pump Specification",
    "equipment_list": "Equipment List",
    "fan_specification": "Fan Specification",
    "hazardous_area_classification": "Hazardous Area Classification",
    "insulation_specification": "Insulation Specification",
    "instrument_list": "Instrument List",
    "io_list": "I/O List",
    "painting_specification": "Painting Specification",
    "performance_curve": "Performance Curve",
    "scr_specification": "SCR Specification",
    "valve_list": "Valve List",
}


@dataclass(frozen=True)
class RuleMatchQuality:
    """Diagnostics for one validation-rule match decision."""

    query: str
    query_source: str = ""
    query_family: str = ""
    rule_family: str = ""
    query_subtype: str = ""
    rule_subtype: str = ""
    query_scope: str = ""
    rule_scope: str = ""
    rule_scope_type: str = ""
    family_status: str = ""
    subtype_status: str = ""
    scope_status: str = ""
    guard_status: str = "no_match"
    guard_reason: str = ""
    token_score: float = 0.0
    semantic_score: float = 0.0
    hybrid_score: float = 0.0
    final_score: float = 0.0
    rule_priority: int = 0

    def output_fields(self) -> dict[str, str]:
        """Return stable string fields for generated schedule outputs."""
        return {
            "rule_match_query_source": self.query_source,
            "rule_match_query_family": self.query_family,
            "rule_match_rule_family": self.rule_family,
            "rule_match_query_subtype": self.query_subtype,
            "rule_match_rule_subtype": self.rule_subtype,
            "rule_match_query_scope": self.query_scope,
            "rule_match_rule_scope": self.rule_scope,
            "rule_match_rule_scope_type": self.rule_scope_type,
            "rule_match_family_status": self.family_status,
            "rule_match_subtype_status": self.subtype_status,
            "rule_match_scope_status": self.scope_status,
            "rule_match_guard_status": self.guard_status,
            "rule_match_guard_reason": self.guard_reason,
            "rule_match_token_score": _fmt_score(self.token_score),
            "rule_match_semantic_score": _fmt_score(self.semantic_score),
            "rule_match_hybrid_score": _fmt_score(self.hybrid_score),
            "rule_match_final_score": _fmt_score(self.final_score),
        }


def build_rule_query(row: dict[str, str]) -> str:
    """Build the validation-rule match query: normalize(Deliverable) + 'for' + abbreviated scope.

    Single source of truth — used both for pre-matching and for the per-row output
    so the query string can never drift between passes.
    """
    deliverable = refine_deliverable_with_title(
        row.get("Deliverable", "").strip(),
        row.get("Title", "").strip(),
    )
    norm_del = _rule_query_deliverable(deliverable, row.get("Title", "").strip())
    scope = (
        row.get("Equipment", "").strip()
        or row.get("System", "").strip()
        or row.get("Building", "").strip()
    )
    abbr_scope = equipment_to_abbr(scope)
    return f"{norm_del} for {abbr_scope}" if abbr_scope else norm_del


class RuleMatcher:
    """Selects the best validation rule for a query via hybrid token + semantic scoring."""

    def __init__(self, lexical: RuleLexicalIndex) -> None:
        self._lexical = lexical
        self._rule_scope_key_cache = {
            id(rule): _scope_keys(
                f"{rule.item_name} {rule.doc_keyword}",
                set(rule._item_tokens) | set(rule._doc_kw_tokens),
            )
            for rule in lexical.rules
        }

    @property
    def rules(self) -> list[ValidationRule]:
        """Loaded validation rules, in CSV order (parallel to semantic embeddings)."""
        return self._lexical.rules

    def match_with_embedding(
        self,
        document: str,
        rule_similarities: list[float],
        equipment: str = "",
        semantic_weight: float = 0.5,
    ) -> ValidationRule | None:
        """Return the best rule using a hybrid token + semantic score.

        Args:
            rule_similarities: cosine similarities, one per rule in self.rules order.
            semantic_weight:   0 = token-only, 1 = semantic-only.
        """
        rule, _quality = self.match_with_embedding_quality(document, rule_similarities, equipment, semantic_weight)
        return rule

    def match_with_embedding_quality(
        self,
        document: str,
        rule_similarities: list[float],
        equipment: str = "",
        semantic_weight: float = 0.5,
        query_source: str = "",
    ) -> tuple[ValidationRule | None, RuleMatchQuality]:
        """Return the best rule plus diagnostics for quality/confidence reporting."""
        doc_tokens = self._lexical.query_tokens(document, equipment)
        candidates = self._ranked_lexical_candidates(doc_tokens)

        query_family, query_subtype = _deliverable_type(document)
        query_scope_tokens = _scope_keys(document, doc_tokens)
        match_candidates: list[tuple[float, ValidationRule, RuleMatchQuality]] = []
        best_rule: ValidationRule | None = None
        best_quality = _empty_quality(document, doc_tokens, query_source)
        best_rejected: RuleMatchQuality | None = None
        for rule in candidates:
            token_score = self._lexical.token_score(rule, doc_tokens)
            sem_score = max(rule_similarities[self._lexical.rule_position(rule)], 0.0)

            hybrid = token_score * (1.0 - semantic_weight) + sem_score * semantic_weight
            final = hybrid * _PRIORITY_WEIGHT.get(rule.priority, 0.60)
            rule_scope_tokens = self._rule_scope_key_cache[id(rule)]
            guard_status, guard_reason = _rule_guard_status(
                document,
                doc_tokens,
                rule,
                query_family=query_family,
                query_subtype=query_subtype,
                query_scope_tokens=query_scope_tokens,
                rule_scope_tokens=rule_scope_tokens,
            )
            quality = _quality_for_rule(
                document=document,
                doc_tokens=doc_tokens,
                rule=rule,
                query_source=query_source,
                token_score=token_score,
                semantic_score=sem_score,
                hybrid_score=hybrid,
                final_score=final,
                guard_status=guard_status,
                guard_reason=guard_reason,
                query_family=query_family,
                query_subtype=query_subtype,
                query_scope_tokens=query_scope_tokens,
                rule_scope_tokens=rule_scope_tokens,
            )
            if guard_status != "passed":
                if best_rejected is None or quality.final_score > best_rejected.final_score:
                    best_rejected = quality
                continue
            # Require minimum token overlap (avoids pure-semantic false positives)
            if token_score == 0.0:
                continue
            if final < 0.2:
                continue
            match_candidates.append((final, rule, quality))

        best = self._select_best_match(match_candidates, doc_tokens, query_family, query_subtype)
        if best:
            best_rule, best_quality = best
        if best_rule is None and best_rejected is not None:
            return None, best_rejected
        return best_rule, best_quality

    def _ranked_lexical_candidates(self, doc_tokens: set[str]) -> list[ValidationRule]:
        scored = [
            (self._lexical.token_score(rule, doc_tokens), rule.priority, rule)
            for rule in self._lexical.candidates(doc_tokens)
        ]
        scored = [item for item in scored if item[0] > 0.0]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [rule for _score, _priority, rule in scored[:_MAX_RULE_CANDIDATES]]

    def _select_best_match(
        self,
        candidates: list[tuple[float, ValidationRule, RuleMatchQuality]],
        doc_tokens: set[str],
        query_family: str,
        query_subtype: str,
    ) -> tuple[ValidationRule, RuleMatchQuality] | None:
        """Select the best passed rule, preferring exact technical-spec family over compatible fallbacks."""
        if not candidates:
            return None
        pool = candidates
        if query_family == "specification":
            exact = [item for item in candidates if item[2].rule_family == "specification"]
            subtype_exact = [item for item in exact if item[2].rule_subtype == query_subtype]
            if subtype_exact:
                exact = subtype_exact
            if exact:
                pool = exact
            schedulable_exact = [item for item in pool if item[1].sub_type != "SKIP"]
            if schedulable_exact:
                pool = schedulable_exact

        best_score, best_rule, best_quality = pool[0]
        for final, rule, quality in pool[1:]:
            if final > best_score:
                best_score, best_rule, best_quality = final, rule, quality
            elif final == best_score:
                tiebreak_rule = self._tiebreak(best_rule, rule, doc_tokens)
                if tiebreak_rule is rule:
                    best_score, best_rule, best_quality = final, rule, quality
        return best_rule, best_quality

    @staticmethod
    def _tiebreak(
        current: ValidationRule, candidate: ValidationRule, doc_tokens: set[str]
    ) -> ValidationRule:
        """Break a score tie: prefer item_name context fit, then higher priority."""
        cand_item_ok = not candidate._item_tokens or bool(candidate._item_tokens & doc_tokens)
        curr_item_ok = not current._item_tokens or bool(current._item_tokens & doc_tokens)
        if cand_item_ok and not curr_item_ok:
            return candidate
        if cand_item_ok == curr_item_ok and candidate.priority < current.priority:
            return candidate
        return current


def resolve_rules(
    rows: list[dict[str, str]],
    matcher: RuleMatcher | None,
    semantic_index: RuleSemanticIndex | None,
    semantic_weight: float = 0.3,
) -> list[ValidationRule | None]:
    """Resolve the validation rule for every row using mandatory hybrid token + semantic match.

    - no matcher → all None (graceful degradation when the rule file is missing)
    - otherwise  → hybrid token + embedding match (semantic_index is required)
    """
    if matcher is None:
        return [None] * len(rows)
    if semantic_index is None:
        raise ValueError("resolve_rules requires a semantic_index when a rule matcher is present")
    rules, _qualities = resolve_rule_matches(rows, matcher, semantic_index, semantic_weight)
    return rules


def resolve_rule_matches(
    rows: list[dict[str, str]],
    matcher: RuleMatcher | None,
    semantic_index: RuleSemanticIndex | None,
    semantic_weight: float = 0.3,
) -> tuple[list[ValidationRule | None], list[RuleMatchQuality]]:
    """Resolve validation rules and match-quality diagnostics for every row."""
    if matcher is None:
        return [None] * len(rows), [_empty_quality(build_rule_query(row), set(), "rule_query") for row in rows]
    if semantic_index is None:
        raise ValueError("resolve_rule_matches requires a semantic_index when a rule matcher is present")
    return _match_rules_semantic(rows, matcher, semantic_index, semantic_weight)


def _match_rules_semantic(
    rows: list[dict[str, str]],
    matcher: RuleMatcher,
    semantic_index: RuleSemanticIndex,
    semantic_weight: float,
) -> tuple[list[ValidationRule | None], list[RuleMatchQuality]]:
    """Batch-embed all rule queries and return hybrid-matched rules for each row."""
    import numpy as np

    from common.embedding_client import AzureEmbeddingService
    from schedule_service.generate._shared.embedding_cache import embed_texts_cached

    # (rule_query, title) per row — same logic as the token path's queries.
    query_pairs = [(build_rule_query(row), row.get("Title", "").strip()) for row in rows]

    # Deduplicate queries to minimise embedding API calls.
    all_queries = [q for pair in query_pairs for q in pair]
    unique_queries = list(dict.fromkeys(all_queries))
    logger.info(
        "Semantic rule matching: embedding {} unique queries for {} rows",
        len(unique_queries), len(rows),
    )

    service = AzureEmbeddingService()
    raw_embeddings = embed_texts_cached(service, unique_queries)
    # score_matrix normalises rows internally → cosine similarity (n_unique, n_rules).
    all_sims = semantic_index.score_matrix(np.array(raw_embeddings, dtype=np.float32))
    query_to_idx = {q: i for i, q in enumerate(unique_queries)}

    def sims_for(query: str) -> list[float]:
        return all_sims[query_to_idx[query]].tolist()

    results: list[ValidationRule | None] = []
    qualities: list[RuleMatchQuality] = []
    for rule_query, title in query_pairs:
        rule, quality = matcher.match_with_embedding_quality(
            rule_query,
            sims_for(rule_query),
            semantic_weight=semantic_weight,
            query_source="rule_query",
        )
        if rule is None:
            title_rule, title_quality = matcher.match_with_embedding_quality(
                title,
                sims_for(title),
                semantic_weight=semantic_weight,
                query_source="title",
            )
            if title_rule is not None or title_quality.final_score > quality.final_score:
                rule = title_rule
                quality = title_quality
        results.append(rule)
        qualities.append(quality)
    return results, qualities


def _rule_guard_status(
    document: str,
    doc_tokens: set[str],
    rule: ValidationRule,
    query_family: str | None = None,
    query_subtype: str | None = None,
    query_scope_tokens: set[str] | None = None,
    rule_scope_tokens: set[str] | None = None,
) -> tuple[str, str]:
    """Return passed/rejected and the reason for obvious validation-rule false positives."""
    if query_family is None or query_subtype is None:
        query_family, query_subtype = _deliverable_type(document)
    rule_family, rule_subtype = _rule_deliverable_type(rule)
    if query_subtype == "painting_specification":
        logger.trace(
            "Rule rejected by blocked-family guard: query='{}' rule='{}' ({})",
            document,
            rule.doc_keyword,
            query_family,
        )
        return "rejected", "blocked_deliverable_family"
    if query_scope_tokens is None:
        query_scope_tokens = _scope_keys(document, doc_tokens)
    if query_scope_tokens:
        if rule_scope_tokens is None:
            rule_scope_tokens = _rule_scope_keys(rule)
        # Equipment-specific rules should not win for a different equipment scope
        # (e.g. "P&ID for ACC" must not match "HRSG - P&ID for SCR").
        if rule_scope_tokens and not query_scope_tokens.intersection(rule_scope_tokens):
            logger.trace(
                "Rule rejected by scope guard: query='{}' rule='{}' ({} vs {})",
                document,
                rule.doc_keyword,
                sorted(query_scope_tokens),
                sorted(rule_scope_tokens),
            )
            return "rejected", "scope_mismatch"
    subtype_status = _subtype_status(query_family, query_subtype, rule_family, rule_subtype)
    if subtype_status == "mismatch":
        logger.trace(
            "Rule rejected by deliverable subtype guard: query='{}' rule='{}' ({} -> {})",
            document,
            rule.doc_keyword,
            query_subtype,
            rule_subtype,
        )
        return "rejected", "deliverable_subtype_mismatch"
    if query_family in _STRICT_FAMILY_MATCH and not rule_family:
        logger.trace(
            "Rule rejected by missing-family guard: query='{}' rule='{}' ({})",
            document,
            rule.doc_keyword,
            query_family,
        )
        return "rejected", "missing_rule_family"
    if query_family and rule_family and not _families_compatible(query_family, rule_family):
        logger.trace(
            "Rule rejected by deliverable guard: query='{}' rule='{}' ({} -> {})",
            document,
            rule.doc_keyword,
            query_family,
            rule_family,
        )
        return "rejected", "deliverable_family_mismatch"

    if (
        query_scope_tokens
        and query_family in _STRICT_FAMILY_MATCH
        and query_family == rule_family
        and not rule_scope_tokens
        and _is_specific_rule_text(rule.doc_keyword)
    ):
        logger.trace(
            "Rule rejected by implicit-scope guard: query='{}' rule='{}' ({})",
            document,
            rule.doc_keyword,
            sorted(query_scope_tokens),
        )
        return "rejected", "implicit_scope_mismatch"
    if _object_token_mismatch(document, doc_tokens, rule, query_family, query_subtype, rule_family, rule_subtype):
        logger.trace(
            "Rule rejected by object-token guard: query='{}' rule='{}'",
            document,
            rule.doc_keyword,
        )
        return "rejected", "object_token_mismatch"
    return "passed", ""


def _empty_quality(document: str, doc_tokens: set[str], query_source: str = "") -> RuleMatchQuality:
    query_scope = sorted(_scope_keys(document, doc_tokens))
    query_family, query_subtype = _deliverable_type(document)
    return RuleMatchQuality(
        query=document,
        query_source=query_source,
        query_family=query_family,
        query_subtype=query_subtype,
        query_scope="|".join(query_scope),
        scope_status="query_unscoped" if not query_scope else "no_rule",
    )


def _quality_for_rule(
    document: str,
    doc_tokens: set[str],
    rule: ValidationRule,
    query_source: str,
    token_score: float,
    semantic_score: float,
    hybrid_score: float,
    final_score: float,
    guard_status: str,
    guard_reason: str,
    query_family: str | None = None,
    query_subtype: str | None = None,
    query_scope_tokens: set[str] | None = None,
    rule_scope_tokens: set[str] | None = None,
) -> RuleMatchQuality:
    if query_family is None or query_subtype is None:
        query_family, query_subtype = _deliverable_type(document)
    rule_family, rule_subtype = _rule_deliverable_type(rule)
    if query_scope_tokens is None:
        query_scope_tokens = _scope_keys(document, doc_tokens)
    if rule_scope_tokens is None:
        rule_scope_tokens = _rule_scope_keys(rule)
    return RuleMatchQuality(
        query=document,
        query_source=query_source,
        query_family=query_family,
        rule_family=rule_family,
        query_subtype=query_subtype,
        rule_subtype=rule_subtype,
        query_scope="|".join(sorted(query_scope_tokens)),
        rule_scope="|".join(sorted(rule_scope_tokens)),
        rule_scope_type=_rule_scope_type(rule),
        family_status=_family_status(query_family, rule_family),
        subtype_status=_subtype_status(query_family, query_subtype, rule_family, rule_subtype),
        scope_status=_scope_status(query_scope_tokens, rule_scope_tokens),
        guard_status=guard_status,
        guard_reason=guard_reason,
        token_score=token_score,
        semantic_score=semantic_score,
        hybrid_score=hybrid_score,
        final_score=final_score,
        rule_priority=rule.priority,
    )


def _rule_scope_type(rule: ValidationRule) -> str:
    rule_scope_tokens = _rule_scope_keys(rule)
    if rule_scope_tokens:
        return "scoped"
    if _is_specific_rule_text(rule.doc_keyword):
        return "implicit_specific"
    return "generic"


def _family_status(query_family: str, rule_family: str) -> str:
    if not query_family and not rule_family:
        return "unknown"
    if not query_family:
        return "missing_query_family"
    if not rule_family:
        return "missing_rule_family"
    if query_family == rule_family:
        return "match"
    return "compatible" if _families_compatible(query_family, rule_family) else "mismatch"


def _scope_status(query_scope_tokens: set[str], rule_scope_tokens: set[str]) -> str:
    if not query_scope_tokens:
        return "query_unscoped"
    if not rule_scope_tokens:
        return "rule_generic"
    return "match" if query_scope_tokens.intersection(rule_scope_tokens) else "mismatch"


def _object_token_mismatch(
    document: str,
    query_tokens: set[str],
    rule: ValidationRule,
    query_family: str,
    query_subtype: str,
    rule_family: str,
    rule_subtype: str,
) -> bool:
    if query_family != rule_family:
        return False
    if query_subtype != rule_subtype:
        return False
    query_content = _content_tokens(query_tokens | _free_text_tokens(document))
    rule_content = _content_tokens(set(rule._item_tokens) | set(rule._doc_kw_tokens))
    if not query_content or not rule_content:
        return False
    if query_content.intersection(rule_content):
        return False
    if query_subtype not in _GENERIC_SUBTYPES:
        return True
    return query_family in {"diagram", "specification", "list", "report", "drawing"}


def _content_tokens(tokens: set[str]) -> set[str]:
    return {
        token
        for token in tokens
        if token
        and token not in _GENERIC_RULE_TOKENS
        and token not in _SCOPE_TOKENS
        and len(token) > 1
        and not token.isdigit()
    }


def _free_text_tokens(value: str) -> set[str]:
    return set(_norm_scope_text(value).lower().split())


def _families_compatible(query_family: str, rule_family: str) -> bool:
    if query_family == rule_family:
        return True
    if query_family in _STRICT_FAMILY_MATCH or rule_family in _STRICT_FAMILY_MATCH:
        return False
    if query_family == "specification" and rule_family in {"datasheet", "description"}:
        return True
    if query_family == "datasheet" and rule_family == "specification":
        return True
    if query_family == "drawing" and rule_family in {"diagram"}:
        return True
    return query_family == "diagram" and rule_family in {"drawing"}


def _rule_query_deliverable(deliverable: str, title: str) -> str:
    family, subtype = canonical_deliverable_type(deliverable=deliverable, title=title)
    if subtype in _SUBTYPE_LABELS:
        return _SUBTYPE_LABELS[subtype]
    return normalize_deliverable(deliverable)


def _deliverable_type(value: str) -> tuple[str, str]:
    return canonical_deliverable_type(deliverable=value, title=value)


def _rule_deliverable_type(rule: ValidationRule) -> tuple[str, str]:
    return rule.canonical_deliverable_family, rule.canonical_deliverable_subtype


def _subtype_status(query_family: str, query_subtype: str, rule_family: str, rule_subtype: str) -> str:
    if not query_subtype or not rule_subtype:
        return "unknown"
    if query_subtype == rule_subtype:
        return "match"
    if query_family != rule_family:
        return "not_applicable"
    if query_subtype in _GENERIC_SUBTYPES and rule_subtype in _GENERIC_SUBTYPES:
        return "compatible"
    if query_subtype in _GENERIC_SUBTYPES or rule_subtype in _GENERIC_SUBTYPES:
        return "mismatch"
    return "mismatch"


def _scope_keys(text: str, tokens: set[str] | None = None) -> set[str]:
    normalized = _norm_scope_text(text)
    keys = {
        key
        for key, aliases in _SCOPE_PATTERNS
        if any(_scope_alias_matches(normalized, alias) for alias in aliases)
    }
    if tokens:
        keys |= tokens & _SCOPE_TOKENS
    return keys


def _rule_scope_keys(rule: ValidationRule) -> set[str]:
    text = f"{rule.item_name} {rule.doc_keyword}"
    return _scope_keys(text, set(rule._item_tokens) | set(rule._doc_kw_tokens))


def _scope_alias_matches(text: str, alias: str) -> bool:
    normalized = _norm_scope_text(alias)
    if not normalized:
        return False
    if re.fullmatch(r"[A-Z0-9]+", normalized):
        return bool(re.search(rf"(?<![A-Z0-9]){re.escape(normalized)}(?![A-Z0-9])", text))
    return normalized in text


def _norm_scope_text(value: str) -> str:
    text = value.upper().replace("&", " AND")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_specific_rule_text(value: str) -> bool:
    text = value.upper()
    return " FOR " in text or " - " in text or "_" in text


def _fmt_score(value: float) -> str:
    return f"{value:.4f}" if value else ""
