"""Load and match MDL validation rules against document titles."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from schedule_service.vt_parser import parse_validation_time

DEFAULT_RULE_PATH = Path("data/schedule_sources/rules/validation_rule_clean.csv")

_TOKEN_RE = re.compile(r"[a-z0-9&]+")
_MIN_TOKEN_LEN = 2

# Reverse aliases: if ALL tokens of an equipment's full name are present in the
# query, add the abbreviation used in validation_rule.csv keywords.
# Only reverse (full name → abbrev) is applied — forward (abbrev → individual
# full-name tokens) is intentionally omitted because generic words like "gas"
# or "steam" create false overlaps with unrelated rules (e.g. N2 Gas System).
_FULL_TO_ABBR: list[tuple[frozenset[str], str]] = [
    (frozenset({"heat", "recovery", "steam", "generator"}), "hrsg"),
    (frozenset({"gas", "turbine", "generator"}),            "gtg"),
    (frozenset({"gas", "turbine"}),                         "gt"),
    (frozenset({"steam", "turbine", "generator"}),          "stg"),
    (frozenset({"air", "cooled", "condenser"}),             "acc"),
    (frozenset({"condensate", "extraction", "pump"}),       "cep"),
    (frozenset({"boiler", "feed", "pump"}),                 "bfp"),
    (frozenset({"fuel", "gas", "package"}),                 "fgp"),
    (frozenset({"balance", "plant"}),                       "bop"),
]


def _expand_query_tokens(tokens: set[str]) -> frozenset[str]:
    """Add equipment abbreviations to the query when all full-name tokens are present.

    Queries with abbreviations already contain the right token (e.g. "hrsg") and
    match HRSG rules directly.  This function handles the reverse case: a query
    title like "Heat Recovery Steam Generator General Arrangement" that contains no
    abbreviation gets "hrsg" injected so it reaches the same HRSG-specific rules.
    """
    extra: set[str] = set()
    for full_tokens, abbr in _FULL_TO_ABBR:
        if full_tokens <= tokens:
            extra.add(abbr)
    if extra:
        return frozenset(tokens | extra)
    return frozenset(tokens)


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
        from schedule_service.vt_parser import describe

        return describe(self.vt_parsed)


def _tokenize(text: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) >= _MIN_TOKEN_LEN}


class RuleTable:
    """Rule table with token inverted index and match cache for fast lookup."""

    def __init__(self, rules: list[ValidationRule]) -> None:
        self._rules = rules
        # token → [rule_index] — built once at init, reduces 5,918 → ~30-100 candidates
        self._index: dict[str, list[int]] = self._build_index()
        # document+equipment → matched rule — cross-row cache for duplicate doc titles
        self._cache: dict[str, ValidationRule | None] = {}

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
