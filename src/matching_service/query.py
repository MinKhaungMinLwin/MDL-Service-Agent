"""Build matching queries from ITB depth values."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from common.text_normalizer import expand_abbreviation_terms

DEPTH_COLUMNS = ("1st Depth", "2nd Depth", "3rd Depth", "4th Depth", "5th Depth")


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    """Return case-insensitive unique values without changing their order."""
    seen = set()
    unique_values = []
    for value in values:
        normalized = value.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(value)
    return unique_values


def get_depth_filter_terms(row: Mapping[str, Any]) -> list[str]:
    """Return non-empty source-grounded ITB depth phrases."""
    terms = []
    for depth in DEPTH_COLUMNS:
        value = str(row.get(depth, "")).strip()
        if not value or value.lower() == "nan":
            continue
        terms.append(value)
    return unique_preserve_order(terms)


def get_depth_context(row: Mapping[str, Any]) -> str:
    """Return the two deepest meaningful ITB terms."""
    depth_terms = get_depth_filter_terms(row)
    return " ".join(depth_terms[-2:])


def get_keyword_terms(row: Mapping[str, Any]) -> list[str]:
    """Return ITB keyword phrases for second-stage candidate ranking."""
    value = str(row.get("Keywords", "")).strip()
    if not value or value.lower() == "nan":
        return []
    terms = [
        term.strip()
        for term in re.split(r"[,;\n]+", value)
        if term.strip() and term.strip().lower() not in {"nan", "none"}
    ]
    return unique_preserve_order(terms)


def build_fulltext_query(terms: list[str]) -> str:
    """Build a Lucene full-text query from source-grounded ITB phrases."""
    clauses = []
    for term in terms:
        normalized_term = re.sub(r"[^A-Za-z0-9]+", " ", term).strip()
        if not normalized_term:
            continue
        clauses.append(f'"{normalized_term}"' if " " in normalized_term else normalized_term)
    return " OR ".join(clauses)


def build_depth_filter_query(row: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Build a Lucene full-text query from ITB depth phrases."""
    terms = get_depth_filter_terms(row)
    return build_fulltext_query(expand_abbreviation_terms(terms)), terms


def build_semantic_query(depth_terms: list[str], keyword_terms: list[str]) -> str:
    """Build one comma-separated semantic query from ITB depth and keywords."""
    return ", ".join(expand_abbreviation_terms([*depth_terms, *keyword_terms]))


def build_cross_encoder_query(
    depth_terms: list[str],
    keyword_terms: list[str] | None = None,
    chunk_text: str = "",
    mode: str = "structured",
    intent_terms: list[str] | None = None,
) -> str:
    """Build the complete ITB context used for cross-encoder scoring."""
    sections = []
    if mode == "full_chunk" and (cleaned_chunk_text := _clean_term(chunk_text)):
        sections.append(f"Chunk Text:\n{cleaned_chunk_text}")
    if depth_terms:
        sections.append(f"Depth:\n{' > '.join(depth_terms)}")
    if keyword_terms:
        sections.append(f"Keywords:\n{'; '.join(keyword_terms)}")
    original_terms = [*depth_terms, *(keyword_terms or [])]
    expanded_terms = expand_abbreviation_terms(original_terms)[len(unique_preserve_order(original_terms)) :]
    if expanded_terms:
        sections.append(f"Expanded terms:\n{'; '.join(expanded_terms)}")
    if intent_terms:
        sections.append(f"Requirement intent:\n{'; '.join(unique_preserve_order(intent_terms))}")
    return "\n\n".join(sections)


def _clean_term(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() == "nan" else text
