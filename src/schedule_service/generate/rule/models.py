"""Data model and tokenization for MDL validation rules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"[a-z0-9&]+")
_MIN_TOKEN_LEN = 2


def tokenize(text: str) -> set[str]:
    """Tokenize text into the lowercased token set used for rule matching."""
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) >= _MIN_TOKEN_LEN}


@dataclass(frozen=True)
class ValidationRule:
    """One MDL validation rule: submission type (FA/FI/SKIP) + VT formula."""

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
        object.__setattr__(self, "_doc_kw_tokens", frozenset(tokenize(combined)))
        object.__setattr__(self, "_item_tokens", frozenset(tokenize(self.item_name)))

    def describe(self) -> str:
        from schedule_service.generate.rule.vt_parser import describe

        return describe(self.vt_parsed)
