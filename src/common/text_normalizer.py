"""Domain text normalization helpers for retrieval."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent / "normalization_rules"
ABBREVIATIONS_PATH = RULES_DIR / "abbreviations.json"


def build_schedule_target_text(activity_name: str, wbs_path: str, activity_id: str) -> str:
    """Build retrieval text for a schedule activity.

    The target keeps the original compact schedule text and appends an expanded
    variant. This preserves exact acronym matching while giving semantic search
    fuller engineering terms to embed.
    """
    original = normalize_space(f"{activity_name} {wbs_path} {activity_id}")
    expanded = expand_schedule_abbreviations(original)
    return join_unique_texts([original, expanded])


def build_schedule_semantic_text(activity_name: str, wbs_path: str) -> str:
    """Build compact semantic text for embedding a schedule activity.

    BM25 benefits from the full WBS path and activity id in ``target_text``. Dense
    embeddings work better with a shorter text that keeps the activity meaning and
    nearby engineering context while dropping generic schedule/root metadata.
    """
    activity = normalize_space(activity_name)
    levels = _semantic_wbs_levels(wbs_path)
    original = join_unique_texts([activity, " ".join(levels)])
    expanded = expand_schedule_abbreviations(original)
    return join_unique_texts([original, expanded])


def expand_schedule_abbreviations(text: str) -> str:
    """Expand known schedule abbreviations without removing the original text."""
    expanded = text
    for abbreviation, full_name in _abbreviations():
        expanded = _replace_token(expanded, abbreviation, full_name)
    return normalize_space(expanded)


def expand_abbreviation_terms(terms: list[str]) -> list[str]:
    """Keep original retrieval terms and append distinct expanded variants."""
    expanded_terms = list(terms)
    expanded_terms.extend(expand_schedule_abbreviations(term) for term in terms)
    return _unique_texts(expanded_terms)


def normalize_space(text: str) -> str:
    """Normalize whitespace and lightweight schedule separators."""
    cleaned = text.replace(">", " ")
    cleaned = re.sub(r"[_\t\r\n]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def join_unique_texts(texts: list[str]) -> str:
    """Join text variants while preserving order and removing duplicates."""
    return " ".join(_unique_texts(texts))


def _semantic_wbs_levels(wbs_path: str, keep_last: int = 3) -> list[str]:
    """Return the most useful WBS levels for dense activity retrieval."""
    raw_levels = re.split(r"\s*>\s*", wbs_path)
    levels = [normalize_space(level) for level in raw_levels if _is_semantic_wbs_level(normalize_space(level))]
    return levels[-keep_last:]


def _is_semantic_wbs_level(level: str) -> bool:
    if not level:
        return False
    lowered = level.casefold()
    generic_parts = (
        "ccpp project standard schedule",
        "standard schedule",
        "idea power plant",
        "block #",
    )
    return not any(part in lowered for part in generic_parts)


def _unique_texts(texts: list[str]) -> list[str]:
    """Return normalized unique text variants while preserving order."""
    seen: set[str] = set()
    unique_texts = []
    for text in texts:
        cleaned = normalize_space(text)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            unique_texts.append(cleaned)
            seen.add(key)
    return unique_texts


@lru_cache(maxsize=1)
def _abbreviations() -> tuple[tuple[str, str], ...]:
    """Load abbreviation replacements."""
    rules = json.loads(ABBREVIATIONS_PATH.read_text(encoding="utf-8"))
    replacements = []
    for canonical, variants in rules.items():
        if isinstance(variants, str):
            replacements.append((canonical, variants))
            continue
        for variant in variants:
            replacements.append((variant, canonical))
    return tuple(sorted(replacements, key=lambda item: len(item[0]), reverse=True))


def _replace_token(text: str, abbreviation: str, full_name: str) -> str:
    """Replace one abbreviation token case-insensitively."""
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(abbreviation)}(?![A-Za-z0-9])", re.IGNORECASE)
    return pattern.sub(full_name, text)
