"""Load and match MDL validation rules against document titles."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from schedule_service.generate.rule_matching.vt_parser import parse_validation_time
from schedule_service.normalizer import expand_query_tokens as _expand_query_tokens

DEFAULT_RULE_PATH = Path("data/schedule_service/processed/validation_rule_clean.csv")

_TOKEN_RE = re.compile(r"[a-z0-9&]+")
_MIN_TOKEN_LEN = 2


_SUB_TYPE_MAP: dict[str, str] = {
    "fa": "FA",
    "ap": "FA",
    "ap: for approval": "FA",
    "fa/fi": "FA",
    "fi": "FI",
    "if": "FI",
    "ifi": "FI",
    "ifr": "FI",
    "if : for information": "FI",
    "as built": "SKIP",
    "unmatch": "SKIP",
}


@dataclass(frozen=True)
class ValidationRule:
    priority: int
    item_name: str
    doc_keyword: str
    activity_keywords: list[str]
    sub_type: str
    vt_parsed: dict
    # Pre-computed at init — avoids re-tokenizing per match call
    _doc_kw_tokens: frozenset = field(default=frozenset(), init=False, repr=False, compare=False)
    # Tokens from item_name only — used in tiebreak to require equipment context
    _item_tokens: frozenset = field(default=frozenset(), init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Combine doc_keyword + item_name so queries without equipment context
        # can't score above threshold against equipment-specific rules.
        combined = f"{self.doc_keyword} {self.item_name}"
        base_tokens = {tok for tok in _TOKEN_RE.findall(combined.lower()) if len(tok) >= _MIN_TOKEN_LEN}
        object.__setattr__(self, "_doc_kw_tokens", frozenset(base_tokens))
        item_tokens = {tok for tok in _TOKEN_RE.findall(self.item_name.lower()) if len(tok) >= _MIN_TOKEN_LEN}
        object.__setattr__(self, "_item_tokens", frozenset(item_tokens))

    def describe(self) -> str:
        from schedule_service.generate.rule_matching.vt_parser import describe

        return describe(self.vt_parsed)


def _tokenize(text: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) >= _MIN_TOKEN_LEN}


# Priority multiplier applied to hybrid scores so specific rules (priority 1)
# beat generic rules (priority 3) even when semantic similarity is slightly higher.
_PRIORITY_WEIGHT: dict[int, float] = {1: 1.0, 2: 0.85, 3: 0.70}


class RuleTable:
    """Rule table with token inverted index and match cache for fast lookup."""

    def __init__(self, rules: list[ValidationRule]) -> None:
        self._rules = rules
        # token → [rule_index] — built once at init, reduces 5,918 → ~30-100 candidates
        self._index: dict[str, list[int]] = self._build_index()
        # id(rule) → list index — for O(1) lookup of semantic embedding by rule object
        self._rule_to_idx: dict[int, int] = {id(r): i for i, r in enumerate(rules)}
        # document+equipment → matched rule — cross-row cache for duplicate doc titles
        self._cache: dict[str, ValidationRule | None] = {}

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

    def _candidates(self, doc_tokens: set[str]) -> list[ValidationRule]:
        """Return rules sharing ≥1 token with doc_tokens via inverted index."""
        seen: set[int] = set()
        result: list[ValidationRule] = []
        for tok in doc_tokens:
            for idx in self._index.get(tok, ()):
                if idx not in seen:
                    seen.add(idx)
                    result.append(self._rules[idx])
        # Fallback: if index yields nothing, score all rules
        return result if result else self._rules

    @classmethod
    def load(cls, path: Path = DEFAULT_RULE_PATH) -> RuleTable:
        """Load validation rules from a semicolon-delimited CSV."""
        rules: list[ValidationRule] = []
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                priority_raw = row.get("Priority", "").strip()
                if not priority_raw or not priority_raw.isdigit():
                    continue
                doc_kw = row.get("MDL Document Keyword", "").strip()
                if not doc_kw:
                    continue
                sub_type_raw = row.get("Pur.", "").strip().lower()
                vt_raw = row.get("Validation Time", "").strip()
                if sub_type_raw in _SUB_TYPE_MAP:
                    sub_type = _SUB_TYPE_MAP[sub_type_raw]
                elif not sub_type_raw:
                    # Pur. is empty — infer from VT formula instead of defaulting to SKIP.
                    # 2896 rules have empty Pur. but valid FA/FC formulas in the CSV.
                    vt_temp = parse_validation_time(vt_raw)
                    sub_type = "FA" if vt_temp.get("has_fa_rule") or vt_temp.get("has_fc_rule") else "SKIP"
                else:
                    sub_type = "SKIP"
                act_kws = [k.strip() for k in row.get("Activity Keyword", "").split("|") if k.strip()]
                raw_item = row.get("Item", "").replace("\xa0", " ").strip()
                rules.append(
                    ValidationRule(
                        priority=int(priority_raw),
                        item_name=raw_item,
                        doc_keyword=doc_kw,
                        activity_keywords=act_kws,
                        sub_type=sub_type,
                        vt_parsed=parse_validation_time(vt_raw),
                    )
                )
        return cls(rules)

    def match(self, document: str, equipment: str = "") -> ValidationRule | None:
        """Return the best matching rule. Results are cached per (document, equipment)."""
        cache_key = f"{document}\x00{equipment}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        doc_tokens = _expand_query_tokens(_tokenize(f"{document} {equipment}"))
        candidates = self._candidates(doc_tokens)

        best_rule: ValidationRule | None = None
        best_score = 0.0
        for rule in candidates:
            kw_tokens = rule._doc_kw_tokens
            if not kw_tokens:
                continue
            inter = len(kw_tokens & doc_tokens)
            if not inter:
                continue
            # Length-normalised recall: divide by max(|kw|, 3) instead of |kw|.
            # This penalises 1–2-token generic rules (e.g. "GENERATOR", "P&ID")
            # that otherwise score recall=1.0 and beat longer, more specific rules.
            # Rules with ≥3 tokens are scored identically to plain recall.
            score = inter / max(len(kw_tokens), 3)
            if score < 0.4:
                continue
            if score > best_score:
                best_score = score
                best_rule = rule
            elif score == best_score and best_rule:
                # Tiebreak: prefer the rule whose item_name tokens actually appear
                # in the query (equipment context present).  If both rules are in
                # the same "item match" state, fall back to priority.
                cand_item_ok = not rule._item_tokens or bool(rule._item_tokens & doc_tokens)
                curr_item_ok = not best_rule._item_tokens or bool(best_rule._item_tokens & doc_tokens)
                if cand_item_ok and not curr_item_ok:
                    # Candidate fits query context, current best does not → swap
                    best_rule = rule
                elif cand_item_ok == curr_item_ok and rule.priority < best_rule.priority:
                    # Same context fit → prefer higher-priority (more specific) rule
                    best_rule = rule

        self._cache[cache_key] = best_rule
        return best_rule

    def match_with_embedding(
        self,
        document: str,
        rule_similarities: list[float],
        equipment: str = "",
        semantic_weight: float = 0.5,
    ) -> ValidationRule | None:
        """Return the best rule using a hybrid token + semantic score.

        Args:
            document:          The query string (rule_query or title).
            rule_similarities: Pre-computed cosine similarities, one per rule
                               in the same order as self._rules.  Call
                               RuleSemanticIndex.score(query_embedding) to get these.
            equipment:         Optional equipment string appended to query tokens.
            semantic_weight:   0 = token-only, 1 = semantic-only.  Default 0.5.
        """
        doc_tokens = _expand_query_tokens(_tokenize(f"{document} {equipment}"))
        candidates = self._candidates(doc_tokens)

        best_rule: ValidationRule | None = None
        best_score = 0.0
        for rule in candidates:
            kw_tokens = rule._doc_kw_tokens
            if not kw_tokens:
                continue
            inter = len(kw_tokens & doc_tokens)
            token_score = inter / max(len(kw_tokens), 3) if inter else 0.0

            rule_idx = self._rule_to_idx[id(rule)]
            sem_score = max(rule_similarities[rule_idx], 0.0)

            hybrid = token_score * (1.0 - semantic_weight) + sem_score * semantic_weight
            # Require minimum token overlap (avoids pure-semantic false positives)
            if token_score < 0.15 and inter == 0:
                continue
            final = hybrid * _PRIORITY_WEIGHT.get(rule.priority, 0.60)
            if final < 0.2:
                continue

            if final > best_score:
                best_score = final
                best_rule = rule
            elif final == best_score and best_rule:
                cand_item_ok = not rule._item_tokens or bool(rule._item_tokens & doc_tokens)
                curr_item_ok = not best_rule._item_tokens or bool(best_rule._item_tokens & doc_tokens)
                better_context = cand_item_ok and not curr_item_ok
                same_context_higher_priority = cand_item_ok == curr_item_ok and rule.priority < best_rule.priority
                if better_context or same_context_higher_priority:
                    best_rule = rule

        return best_rule
