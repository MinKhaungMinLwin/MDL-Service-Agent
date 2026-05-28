"""Load and match MDL validation rules against document titles."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from schedule_service.vt_parser import parse_validation_time

DEFAULT_RULE_PATH = Path("04_data/schedule_sources/rules/validation_rule.csv")

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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_doc_kw_tokens",
            frozenset(tok for tok in _TOKEN_RE.findall(self.doc_keyword.lower()) if len(tok) >= _MIN_TOKEN_LEN),
        )

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
                sub_type = _SUB_TYPE_MAP.get(sub_type_raw, "SKIP")
                vt_raw = row.get("Validation Time", "").strip()
                act_kws = [k.strip() for k in row.get("Activity Keyword", "").split("|") if k.strip()]
                rules.append(
                    ValidationRule(
                        priority=int(priority_raw),
                        item_name=row.get("Item", "").strip(),
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

        doc_tokens = _tokenize(f"{document} {equipment}")
        candidates = self._candidates(doc_tokens)

        best_rule: ValidationRule | None = None
        best_score = 0.0
        for rule in candidates:
            kw_tokens = rule._doc_kw_tokens
            if not kw_tokens:
                continue
            score = len(kw_tokens & doc_tokens) / len(kw_tokens)
            if score < 0.5:
                continue
            if score > best_score or (score == best_score and best_rule and rule.priority < best_rule.priority):
                best_score = score
                best_rule = rule

        self._cache[cache_key] = best_rule
        return best_rule
