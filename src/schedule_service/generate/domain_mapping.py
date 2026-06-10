"""Domain policy mappings for schedule rule/activity validation.

These mappings are intentionally data-driven. They provide a place to encode
document-family policy separately from retrieval scores, and are used by
evaluation/labeling workflows before being promoted into hard matcher guards.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DOMAIN_MAPPING_PATH = Path("data/schedule_service/processed/schedule_domain_mapping.csv")


@dataclass(frozen=True)
class DomainMapping:
    deliverable_family: str
    scope_family: str
    allowed_rule_families: tuple[str, ...]
    allowed_activity_phases: tuple[str, ...]
    anchor_policy: str
    notes: str = ""


def load_domain_mappings(path: Path = DEFAULT_DOMAIN_MAPPING_PATH) -> list[DomainMapping]:
    """Load explicit domain mappings from CSV."""
    with open(path, newline="", encoding="utf-8-sig") as file:
        rows = csv.DictReader(file)
        return [
            DomainMapping(
                deliverable_family=_clean(row.get("deliverable_family")),
                scope_family=_clean(row.get("scope_family")),
                allowed_rule_families=_split(row.get("allowed_rule_families")),
                allowed_activity_phases=_split(row.get("allowed_activity_phases")),
                anchor_policy=_clean(row.get("anchor_policy")),
                notes=str(row.get("notes") or "").strip(),
            )
            for row in rows
            if _clean(row.get("deliverable_family"))
        ]


def find_domain_mapping(
    deliverable_family: str,
    scope_family: str,
    mappings: list[DomainMapping],
) -> DomainMapping | None:
    """Return the most specific mapping for a deliverable/scope family."""
    deliverable = _clean(deliverable_family)
    scope = _clean(scope_family)
    for mapping in mappings:
        if mapping.deliverable_family == deliverable and mapping.scope_family == scope:
            return mapping
    for mapping in mappings:
        if mapping.deliverable_family == deliverable and mapping.scope_family == "*":
            return mapping
    return None


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in str(value or "").split("|") if part.strip())


def _clean(value: str | None) -> str:
    return str(value or "").strip().lower()
