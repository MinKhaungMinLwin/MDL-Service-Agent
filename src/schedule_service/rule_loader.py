"""Load and match MDL validation rules against document titles."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from schedule_service.vt_parser import parse_validation_time

DEFAULT_RULE_PATH = Path("04_data/schedule_sources/rules/validation_rule.csv")

_TOKEN_RE = re.compile(r"[a-z0-9&]+")

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

    def describe(self) -> str:
        from schedule_service.vt_parser import describe
        return describe(self.vt_parsed)


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _score(rule: ValidationRule, doc_tokens: set[str]) -> float:
    """Keyword coverage: fraction of rule keyword tokens found in document."""
    kw_tokens = _tokenize(rule.doc_keyword)
    if not kw_tokens:
        return 0.0
    return len(kw_tokens & doc_tokens) / len(kw_tokens)


class RuleTable:
    """Simple rule table for matching MDL documents to validation rules."""

    def __init__(self, rules: list[ValidationRule]) -> None:
        self._rules = rules

    @classmethod
    def load(cls, path: Path = DEFAULT_RULE_PATH) -> "RuleTable":
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
                rules.append(ValidationRule(
                    priority=int(priority_raw),
                    item_name=row.get("Item", "").strip(),
                    doc_keyword=doc_kw,
                    activity_keywords=act_kws,
                    sub_type=sub_type,
                    vt_parsed=parse_validation_time(vt_raw),
                ))
        return cls(rules)

    def match(self, document: str, equipment: str = "") -> Optional[ValidationRule]:
        """Return the best matching rule for a document title and equipment context."""
        doc_tokens = _tokenize(f"{document} {equipment}")
        best_rule: Optional[ValidationRule] = None
        best_score = 0.0

        for rule in self._rules:
            score = _score(rule, doc_tokens)
            if score < 0.5:
                continue
            # Higher score wins; break ties by lower priority number
            if score > best_score or (
                score == best_score and best_rule and rule.priority < best_rule.priority
            ):
                best_score = score
                best_rule = rule

        return best_rule
