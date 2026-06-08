"""Token inverted index + Jaccard-style scoring for validation rules.

Mirrors activity.lexical (BM25Index): the lexical-retrieval half of rule matching.
Selection / tiebreak / hybrid scoring lives in rule.matcher.
"""

from __future__ import annotations

from schedule_service.generate.rule.models import ValidationRule, tokenize
from schedule_service.normalizer import expand_query_tokens


class RuleLexicalIndex:
    """Inverted token index over validation rules for fast candidate narrowing."""

    def __init__(self, rules: list[ValidationRule]) -> None:
        self._rules = rules
        # token → [rule_index] — reduces ~5,918 rules → ~30-100 candidates per query
        self._index: dict[str, list[int]] = self._build_index()
        # id(rule) → list index — O(1) lookup of a rule's semantic-embedding row
        self._rule_to_idx: dict[int, int] = {id(r): i for i, r in enumerate(rules)}

    @property
    def rules(self) -> list[ValidationRule]:
        """Loaded validation rules, in CSV order (parallel to semantic embeddings)."""
        return self._rules

    def _build_index(self) -> dict[str, list[int]]:
        index: dict[str, list[int]] = {}
        for i, rule in enumerate(self._rules):
            for tok in rule._doc_kw_tokens:
                index.setdefault(tok, []).append(i)
        return index

    def query_tokens(self, document: str, equipment: str = "") -> frozenset[str]:
        """Tokenize a query and inject equipment abbreviations (e.g. HRSG)."""
        return expand_query_tokens(tokenize(f"{document} {equipment}"))

    def candidates(self, doc_tokens: set[str]) -> list[ValidationRule]:
        """Return rules sharing ≥1 token with doc_tokens; all rules if none match."""
        seen: set[int] = set()
        result: list[ValidationRule] = []
        for tok in doc_tokens:
            for idx in self._index.get(tok, ()):
                if idx not in seen:
                    seen.add(idx)
                    result.append(self._rules[idx])
        # Fallback: if the index yields nothing, score all rules
        return result if result else self._rules

    def rule_position(self, rule: ValidationRule) -> int:
        """Return the rule's index in the rule list (aligns with semantic-index rows)."""
        return self._rule_to_idx[id(rule)]

    @staticmethod
    def token_score(rule: ValidationRule, doc_tokens: set[str]) -> float:
        """Length-normalised recall: |kw ∩ doc| / max(|kw|, 3).

        Dividing by max(|kw|, 3) penalises 1–2-token generic rules ("GENERATOR",
        "P&ID") that otherwise score recall=1.0 and beat longer, specific rules.
        Rules with ≥3 tokens are scored identically to plain recall.
        """
        kw_tokens = rule._doc_kw_tokens
        if not kw_tokens:
            return 0.0
        inter = len(kw_tokens & doc_tokens)
        if not inter:
            return 0.0
        return inter / max(len(kw_tokens), 3)
