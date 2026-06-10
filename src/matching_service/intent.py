"""Deterministic ITB requirement intent extraction for MDL matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RequirementIntent:
    """Canonical signals inferred from one ITB chunk."""

    equipment: tuple[str, ...] = ()
    systems: tuple[str, ...] = ()
    deliverables: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    source_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "equipment": list(self.equipment),
            "systems": list(self.systems),
            "deliverables": list(self.deliverables),
            "actions": list(self.actions),
            "constraints": list(self.constraints),
            "source_terms": list(self.source_terms),
        }

    def as_query_terms(self) -> list[str]:
        return [*self.equipment, *self.systems, *self.deliverables, *self.constraints]


_EQUIPMENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Air Cooled Condenser", ("ACC", "AIR COOLED CONDENSER", "AIR-COOLED CONDENSER")),
    ("Heat Recovery Steam Generator", ("HRSG", "HEAT RECOVERY STEAM GENERATOR")),
    ("Gas Turbine Generator", ("GTG", "GAS TURBINE GENERATOR", "GAS TURBINE")),
    ("Steam Turbine Generator", ("STG", "STEAM TURBINE GENERATOR", "STEAM TURBINE")),
    ("Distributed Control System", ("DCS", "DISTRIBUTED CONTROL SYSTEM")),
    ("Continuous Emission Monitoring System", ("CEMS", "CONTINUOUS EMISSION MONITORING")),
    ("Water Treatment System", ("WATER TREATMENT", "WASTE WATER", "WASTEWATER", "SEWAGE TREATMENT")),
)

_SYSTEM_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Hazardous Area", ("HAZARDOUS AREA", "AREA CLASSIFICATION")),
    ("Performance", ("PERFORMANCE", "GUARANTEE", "GUARANTEED")),
    ("Emission Monitoring", ("CEMS", "EMISSION MONITORING")),
    ("Power Metering", ("POWER METERING", "METERING SYSTEM")),
    ("Waste Water Treatment", ("WASTE WATER", "WASTEWATER", "SEWAGE TREATMENT")),
)

_DELIVERABLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Hazardous Area Classification", ("HAZARDOUS AREA CLASSIFICATION", "AREA CLASSIFICATION")),
    ("Performance Correction Curve", ("PERFORMANCE CORRECTION CURVE",)),
    ("Performance Curve", ("PERFORMANCE CURVE", "CAPABILITY CURVE", "CORRECTION CURVE")),
    ("Degradation Curve", ("DEGRADATION CURVE", "DEGRADATION FACTOR")),
    ("Technical Specification", ("TECHNICAL SPECIFICATION", "TECHNICAL SPECIFICATIONS", "SPECIFICATION")),
    ("P&ID", ("P&ID", "P&I DIAGRAM", "PIPING AND INSTRUMENT", "PIPING & INSTRUMENT")),
    ("System Description", ("SYSTEM DESCRIPTION",)),
    ("Functional Design Specification", ("FUNCTIONAL DESIGN SPECIFICATION", "FDS")),
    ("Design Report", ("DESIGN REPORT",)),
    ("CFD Report", ("CFD REPORT",)),
    ("Report", ("REPORT",)),
    ("Process Flow Diagram", ("PROCESS FLOW DIAGRAM", "PFD")),
    ("Control Logic Diagram", ("CONTROL LOGIC DIAGRAM", "LOGIC DIAGRAM")),
    ("Power Distribution Diagram", ("POWER DISTRIBUTION",)),
    ("Diagram", ("DIAGRAM",)),
    ("Datasheet & Drawings", ("DATASHEET & DRAWING", "DATASHEET AND DRAWING", "DATA SHEET & DRAWING")),
    ("Instrument List", ("INSTRUMENT LIST",)),
    ("Equipment List", ("EQUIPMENT LIST",)),
    ("List", (" LIST",)),
    ("General Arrangement", ("GENERAL ARRANGEMENT", "ARRANGEMENT")),
    ("Outline Drawing", ("OUTLINE DRAWING", "OUTLINE")),
    ("Calculation", ("CALCULATION", "CALCULATIONS")),
    ("Procedure", ("PROCEDURE",)),
    ("Manual", ("MANUAL", "O&M")),
)

_ACTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("submit", ("SUBMIT", "SUBMISSION", "DELIVER", "PROVIDE", "FURNISH")),
    ("prepare", ("PREPARE", "ISSUE", "DEVELOP")),
    ("calculate", ("CALCULATE", "CALCULATION", "DETERMINE")),
    ("guarantee", ("GUARANTEE", "GUARANTEED", "WARRANT")),
    ("review", ("REVIEW", "APPROVAL", "APPROVE")),
)

_CONSTRAINT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("post-COD", ("POST-COD", "POST COD", "AFTER COD")),
    ("long-term", ("LONG TERM", "LONG-TERM")),
    ("as-built", ("AS BUILT", "AS-BUILT")),
    ("block-specific", ("BLOCK #", "BLOCK NO", "UNIT #", "UNIT NO")),
    ("plant overall", ("PLANT OVERALL", "OVERALL PLANT", "WHOLE SITE", "ENTIRE PLANT")),
)


def build_requirement_intent(
    row: dict[str, Any] | Any,
    depth_terms: list[str],
    keyword_terms: list[str],
) -> RequirementIntent:
    """Infer structured intent from the existing ITB extraction row."""
    chunk_text = _clean(_get(row, "Chunk Text"))
    source_terms = _unique([*depth_terms, *keyword_terms])
    text = _normalize_text(" ".join([*source_terms, chunk_text]))
    return RequirementIntent(
        equipment=tuple(_match_patterns(text, _EQUIPMENT_PATTERNS)),
        systems=tuple(_match_patterns(text, _SYSTEM_PATTERNS)),
        deliverables=tuple(_match_patterns(text, _DELIVERABLE_PATTERNS)),
        actions=tuple(_match_patterns(text, _ACTION_PATTERNS)),
        constraints=tuple(_match_patterns(text, _CONSTRAINT_PATTERNS)),
        source_terms=tuple(source_terms),
    )


def _match_patterns(text: str, patterns: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    matches = []
    for canonical, aliases in patterns:
        if any(_contains_alias(text, alias) for alias in aliases):
            matches.append(canonical)
    return _unique(matches)


def _contains_alias(text: str, alias: str) -> bool:
    normalized = _normalize_text(alias)
    if not normalized:
        return False
    if re.fullmatch(r"[A-Z0-9&]+", normalized):
        return bool(re.search(rf"(?<![A-Z0-9]){re.escape(normalized)}(?![A-Z0-9])", text))
    return normalized in text


def _normalize_text(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9&#+/-]+", " ", value.upper())
    return re.sub(r"\s+", " ", text).strip()


def _get(row: Any, key: str) -> Any:
    return row.get(key, "") if hasattr(row, "get") else ""


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() == "nan" else text


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result
