"""Domain text normalization helpers for retrieval."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent / "normalization_rules"
SCHEDULE_ABBREVIATIONS_PATH = RULES_DIR / "schedule_abbreviations.json"


def build_schedule_target_text(activity_name: str, wbs_path: str, activity_id: str) -> str:
    """Build retrieval text for a schedule activity.

    The target keeps the original compact schedule text and appends an expanded
    variant. This preserves exact acronym matching while giving semantic search
    fuller engineering terms to embed.
    """
    original = normalize_space(f"{activity_name} {wbs_path} {activity_id}")
    expanded = expand_schedule_abbreviations(original)
    return join_unique_texts([original, expanded])


def expand_schedule_abbreviations(text: str) -> str:
    """Expand known schedule abbreviations without removing the original text."""
    expanded = text
    for abbreviation, full_name in _schedule_abbreviations():
        expanded = _replace_token(expanded, abbreviation, full_name)
    return normalize_space(expanded)


def normalize_space(text: str) -> str:
    """Normalize whitespace and lightweight schedule separators."""
    cleaned = text.replace(">", " ")
    cleaned = re.sub(r"[_\t\r\n]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def join_unique_texts(texts: list[str]) -> str:
    """Join text variants while preserving order and removing duplicates."""
    seen: set[str] = set()
    unique_texts = []
    for text in texts:
        cleaned = normalize_space(text)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            unique_texts.append(cleaned)
            seen.add(key)
    return " ".join(unique_texts)


@lru_cache(maxsize=1)
def _schedule_abbreviations() -> tuple[tuple[str, str], ...]:
    rules = json.loads(SCHEDULE_ABBREVIATIONS_PATH.read_text(encoding="utf-8"))
    replacements = []
    for canonical, variants in rules.items():
        if isinstance(variants, str):
            replacements.append((canonical, variants))
            continue
        for variant in variants:
            replacements.append((variant, canonical))
    return tuple(sorted(replacements, key=lambda item: len(item[0]), reverse=True))


def _replace_token(text: str, abbreviation: str, full_name: str) -> str:
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(abbreviation)}(?![A-Za-z0-9])", re.IGNORECASE)
    return pattern.sub(full_name, text)
