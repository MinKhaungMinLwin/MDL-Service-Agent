"""Build matching queries from ITB depth values."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

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


def build_depth_filter_query(row: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Build a Lucene full-text query from ITB depth phrases."""
    terms = get_depth_filter_terms(row)
    clauses = []
    for term in terms:
        normalized_term = re.sub(r"[^A-Za-z0-9]+", " ", term).strip()
        if not normalized_term:
            continue
        clauses.append(f'"{normalized_term}"' if " " in normalized_term else normalized_term)
    return " OR ".join(clauses), terms


def build_cross_encoder_query(depth_terms: list[str]) -> str:
    """Build a readable depth hierarchy for cross-encoder scoring."""
    return " > ".join(depth_terms)


def build_keyword_ranking_query(keyword_terms: list[str], depth_terms: list[str]) -> str:
    """Build the query used to rank the depth-filtered candidate pool."""
    terms = keyword_terms or depth_terms[-2:]
    return ", ".join(terms)
