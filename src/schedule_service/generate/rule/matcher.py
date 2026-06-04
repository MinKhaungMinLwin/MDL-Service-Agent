"""Validation-rule matching: build the query, then select the best rule.

Combines lexical retrieval (rule.lexical.RuleLexicalIndex) with semantic similarity
(rule.semantic.RuleSemanticIndex) into a single hybrid score, and exposes one entry
point, `resolve_rules`, that returns one rule (or None) per input MDL row. Semantic
matching is mandatory — there is no token-only path.
"""

from __future__ import annotations

from loguru import logger

from schedule_service.generate.rule.lexical import RuleLexicalIndex
from schedule_service.generate.rule.models import ValidationRule
from schedule_service.generate.rule.semantic import RuleSemanticIndex
from schedule_service.normalizer import equipment_to_abbr, normalize_deliverable

# Priority multiplier applied to hybrid scores so specific rules (priority 1)
# beat generic rules (priority 3) even when semantic similarity is slightly higher.
_PRIORITY_WEIGHT: dict[int, float] = {1: 1.0, 2: 0.85, 3: 0.70}


def build_rule_query(row: dict[str, str]) -> str:
    """Build the validation-rule match query: normalize(Deliverable) + 'for' + abbreviated scope.

    Single source of truth — used both for pre-matching and for the per-row output
    so the query string can never drift between passes.
    """
    norm_del = normalize_deliverable(row.get("Deliverable", "").strip())
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
        doc_tokens = self._lexical.query_tokens(document, equipment)
        candidates = self._lexical.candidates(doc_tokens)

        best_rule: ValidationRule | None = None
        best_score = 0.0
        for rule in candidates:
            token_score = self._lexical.token_score(rule, doc_tokens)
            sem_score = max(rule_similarities[self._lexical.rule_position(rule)], 0.0)

            hybrid = token_score * (1.0 - semantic_weight) + sem_score * semantic_weight
            # Require minimum token overlap (avoids pure-semantic false positives)
            if token_score == 0.0:
                continue
            final = hybrid * _PRIORITY_WEIGHT.get(rule.priority, 0.60)
            if final < 0.2:
                continue
            if final > best_score:
                best_score = final
                best_rule = rule
            elif final == best_score and best_rule:
                best_rule = self._tiebreak(best_rule, rule, doc_tokens)

        return best_rule

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
    return _match_rules_semantic(rows, matcher, semantic_index, semantic_weight)


def _match_rules_semantic(
    rows: list[dict[str, str]],
    matcher: RuleMatcher,
    semantic_index: RuleSemanticIndex,
    semantic_weight: float,
) -> list[ValidationRule | None]:
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
    for rule_query, title in query_pairs:
        rule = matcher.match_with_embedding(rule_query, sims_for(rule_query), semantic_weight=semantic_weight)
        if rule is None:
            rule = matcher.match_with_embedding(title, sims_for(title), semantic_weight=semantic_weight)
        results.append(rule)
    return results
