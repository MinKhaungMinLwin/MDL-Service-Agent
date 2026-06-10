"""Central pre-processing layer for data normalization in the CCPP schedule service.

Single source of truth for normalizing the raw data sources (CCPP guide schedule,
validation rules, MDL candidates) into canonical forms *before* they enter the
matching pipeline. Covers two data dimensions:

Equipment names:
- candidate_extractor: raw Matched_Doc_N strings → canonical name
- schedule_generator: canonical name → abbreviation (rule_query construction)
- rule_loader: full-name tokens → abbreviation (query token expansion)

Deliverable names:
- schedule_generator: raw MDL Deliverable → validation_rule.csv keyword form

Changing a mapping here propagates to all consumers automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 1. Raw / abbreviated input → canonical equipment name
#    Used by candidate_extractor when parsing Matched_Doc_N strings.
# ---------------------------------------------------------------------------
_RAW_TO_CANONICAL: dict[str, str] = {
    # Short codes
    "GTG": "Gas Turbine Generator",
    "GT": "Gas Turbine Generator",
    "HRSG": "Heat Recovery Steam Generator",
    "STG": "Steam Turbine & Generator",
    "ST": "Steam Turbine",
    "ACC": "Air Cooled Condenser",
    "BOP": "Balance of Plant",
    "DCS": "DCS",
    "GIS": "GIS",
    "CEP": "Condensate Extraction Pump",
    "BFP": "Boiler Feed Pump",
    "BOP PIPING": "BOP Piping",
    "CCWP": "Cooling Water Package",
    "FGP": "Fuel Gas Package",
    "BSEDG": "Blackstart Emergency Diesel Generator",
    # Full names from Matched_Doc_N underscore-prefixes
    "AIR COOLED CONDENSER": "Air Cooled Condenser",
    "AIR COOLED CONDENSER FOUNDATION": "Air Cooled Condenser",
    "HEAT RECOVERY STEAM GENERATOR": "Heat Recovery Steam Generator",
    "HEAT RECOVERY STEAM GENERATOR FOUNDATION": "Heat Recovery Steam Generator",
    "GAS TURBINE GENERATOR": "Gas Turbine Generator",
    "GAS TURBINE": "Gas Turbine Generator",
    "STEAM TURBINE & GENERATOR": "Steam Turbine & Generator",
    "STEAM TURBINE GENERATOR": "Steam Turbine & Generator",
    "STEAM TURBINE": "Steam Turbine",
    "CONDENSATE EXTRACTION PUMP": "Condensate Extraction Pump",
    "CONDENSER VACUUM PUMP": "Condenser Vacuum Pump",
    "CEP & CONDENSER FOUNDATION": "Steam Turbine",
    "CONDENSER TUBE CLEANING SYSTEM": "Steam Turbine",
    "BOILER FEED PUMP": "Boiler Feed Pump",
    "FIN FAN COOLER": "Fin Fan Cooler",
    "FIN FAN": "Fin Fan Cooler",
    "AIR COMPRESSOR": "Air Compressor",
    "FUEL GAS SUPPLY SYSTEM": "Fuel Gas Package",
    "FUEL GAS STATION FOUNDATION": "Fuel Gas Package",
    "WTP": "Water Treatment Plant",
    "WATER TREATMENT PLANT": "Water Treatment Plant",
    "WASTE WATER TREATMENT PLANT": "Water Treatment Plant",
    "WASTE WATER TREATMENT": "Water Treatment Plant",
    "WATER TREATMENT": "Water Treatment Plant",
    "ULSD STORAGE TANK FOUNDATION": "Fuel Oil System",
    "FUEL OIL FALSE START STORAGE TANK PIT": "Fuel Oil System",
    "HVAC SYSTEM": "HVAC",
}

# ---------------------------------------------------------------------------
# 2. Ordered scan for equipment keywords in plain document titles
#    Longest / most specific first to avoid partial matches.
#    Used by candidate_extractor when no separator is found in the raw string.
# ---------------------------------------------------------------------------
EQUIPMENT_SCAN: list[tuple[str, str]] = [
    ("HEAT RECOVERY STEAM GENERATOR", "Heat Recovery Steam Generator"),
    ("AIR COOLED CONDENSER",          "Air Cooled Condenser"),
    ("GAS TURBINE GENERATOR",         "Gas Turbine Generator"),
    ("STEAM TURBINE & GENERATOR",     "Steam Turbine & Generator"),
    ("STEAM TURBINE GENERATOR",       "Steam Turbine & Generator"),
    ("CONDENSATE EXTRACTION PUMP",    "Condensate Extraction Pump"),
    ("CONDENSER VACUUM PUMP",         "Condenser Vacuum Pump"),
    ("WATER TREATMENT PLANT",         "Water Treatment Plant"),
    ("WASTE WATER TREATMENT",         "Water Treatment Plant"),
    ("BOILER FEED PUMP",              "Boiler Feed Pump"),
    ("FIN FAN COOLER",                "Fin Fan Cooler"),
    ("AIR COMPRESSOR",                "Air Compressor"),
    ("STEAM TURBINE",                 "Steam Turbine"),
    ("GAS TURBINE",                   "Gas Turbine Generator"),
    ("FUEL OIL",                      "Fuel Oil System"),
    ("FUEL GAS",                      "Fuel Gas Package"),
    ("HRSG",                          "Heat Recovery Steam Generator"),
    ("GTG",                           "Gas Turbine Generator"),
    ("STG",                           "Steam Turbine & Generator"),
    ("CEP",                           "Condensate Extraction Pump"),
    ("BFP",                           "Boiler Feed Pump"),
    ("GIS",                           "GIS"),
    ("DCS",                           "DCS"),
    ("ACC",                           "Air Cooled Condenser"),
    ("BOP",                           "Balance of Plant"),
]

# ---------------------------------------------------------------------------
# 3. Canonical equipment name → abbreviation used in validation_rule.csv
#    Used by schedule_generator when building the rule_query string so that
#    "Heat Recovery Steam Generator" becomes "HRSG" and matches HRSG-keyed rules.
# ---------------------------------------------------------------------------
CANONICAL_TO_ABBR: dict[str, str] = {
    "Heat Recovery Steam Generator":        "HRSG",
    "Gas Turbine Generator":                "GTG",
    "Steam Turbine & Generator":            "STG",
    "Steam Turbine":                        "STG",
    "Air Cooled Condenser":                 "ACC",
    "Condensate Extraction Pump":           "CEP",
    "Boiler Feed Pump":                     "BFP",
    "Fuel Gas Package":                     "FGP",
    "Balance of Plant":                     "BOP",
    "Cooling Water Package":                "CCWP",
    "Blackstart Emergency Diesel Generator": "BSEDG",
}

# ---------------------------------------------------------------------------
# 4. Full-name token set → abbreviation (for rule query token expansion)
#    Used by rule_loader._expand_query_tokens.
#    Reverse-only: inject abbreviation when all full-name tokens are in query.
#    Forward direction (abbrev → individual tokens) is intentionally omitted
#    because generic words like "gas" or "steam" create false overlaps.
# ---------------------------------------------------------------------------
FULL_NAME_TO_ABBR_TOKENS: list[tuple[frozenset[str], str]] = [
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

# ---------------------------------------------------------------------------
# 5. Raw MDL Deliverable value → term used in validation_rule.csv keywords
#    Used by schedule_generator when building the rule_query string so that
#    "P&I DIAGRAM" matches P&ID-keyed rules, "GA" matches General Arrangement, etc.
# ---------------------------------------------------------------------------
_DELIVERABLE_TO_RULE_KEYWORD: dict[str, str] = {
    "P&I DIAGRAM": "P&ID",
    "P&I DRAWING": "P&ID",
    "P&ID": "P&ID",
    "PIPING & INSTRUMENTATION DRAWING": "P&ID",
    "PIPING AND INSTRUMENTATION DRAWING": "P&ID",
    "PIPING AND INSTRUMENTATION DIAGRAM": "P&ID",
    "GENERAL ARRANGEMENT": "General Arrangement Drawing",
    "GA": "General Arrangement Drawing",
    "GA DRAWING": "General Arrangement Drawing",
    "ARRANGEMENT DRAWING": "General Arrangement Drawing",
    "LAYOUT": "Layout Drawing",
    "LAYOUT DRAWING": "Layout Drawing",
    "CALCULATION": "Calculation sheet",
    "SIZING CALCULATION": "Calculation sheet",
    "PAINTING SPECIFICATION": "Painting Specification",
    "PAINT SPECIFICATION": "Painting Specification",
    "TECHNICAL SPECIFICATION": "Technical Specification",
    "SPECIFICATION": "Technical Specification",
    "DATA SHEET": "Data Sheet",
    "DATASHEET": "Data Sheet",
    "GENERATOR CAPABILITY CURVES AND DATA": "Generator Capability Curves and Data",
    "CAPABILITY CURVES AND DATA": "Generator Capability Curves and Data",
    "CAPABILITY CURVES": "Generator Capability Curves and Data",
    "PERFORMANCE DATA AND CURVES": "Performance Data and Curves",
    "PERFORMANCE CURVES": "Performance Curve",
    "PERFORMANCE CURVE": "Performance Curve",
    "PERFORMANCE DATA": "Performance Data and Curves",
    "CURVES": "Performance Curve",
    "CURVE": "Performance Curve",
    "OUTLINE DRAWING": "Outline Drawing",
    "SINGLE LINE DIAGRAM": "Single Line Diagram",
    "SLD": "Single Line Diagram",
    "DETAIL": "Detail Drawing",
    "DETAIL DRAWING": "Detail Drawing",
    "ELEVATION": "Elevation Drawing",
    "DIAGRAM": "Diagram",
    "ISOMETRIC": "Isometric Drawing",
    "ISOMETRIC DRAWING": "Isometric Drawing",
    "FOUNDATION AND LOADING DATA": "Foundation and Loading Data",
    "SYSTEM DESCRIPTION": "System Description",
    "PLAN": "Plan",
    "SCHEDULE": "Schedule",
}

# ---------------------------------------------------------------------------
# 6. Ordered scan for deliverable-type keywords in raw document text
#    Longest / most specific first to avoid partial matches.
#    Used by candidate_extractor to extract the deliverable type from a raw
#    Matched_Doc_N title (or equipment prefix) parsed from ITB matching output.
# ---------------------------------------------------------------------------
_DELIVERABLE_SCAN_KEYWORDS: list[str] = [
    # P&ID variants
    "P&I DIAGRAM", "P&ID", "PIPING AND INSTRUMENTATION DIAGRAM", "PIPING & INSTRUMENTATION DRAWING",
    # Arrangement / Layout
    "GENERAL ARRANGEMENT DRAWING", "GENERAL ARRANGEMENT", "GA DRAWING",
    "PIPING ARRANGEMENT DRAWING", "ARRANGEMENT DRAWING", "ARRANGEMENT",
    "LAYOUT DRAWING", "LAYOUT",
    # Electrical / Control diagrams (longest first to avoid partial match)
    "ELECTRICAL CONTROL LOGIC DIAGRAM",
    "FUNCTIONAL LOOP DIAGRAM",
    "CONTROL LOOP DIAGRAM",
    "CONTROL LOGIC DIAGRAM",
    "SINGLE LINE DIAGRAM",
    "SCHEMATIC DIAGRAM",
    "WIRING DIAGRAM",
    "LOGIC DIAGRAM",
    # Calculation variants
    "SIZING CALCULATION", "CALCULATION SHEET", "DESIGN CALCULATION", "CALCULATION",
    # Data sheet variants
    "TECHNICAL DATA SHEET", "TECHNICAL DATASHEET", "DATA SHEET", "DATASHEET",
    # Drawings
    "OUTLINE DRAWING", "ISOMETRIC DRAWING", "DETAIL DRAWING", "SECTIONAL DRAWING",
    "PIPING ISO DRAWING", "ELEVATION", "PLAN & SECTION", "PLAN AND SECTION",
    "DRAWING",
    # Specification / Criteria / Requirements
    "PAINTING SPECIFICATION", "PAINT SPECIFICATION",
    "TECHNICAL SPECIFICATIONS", "TECHNICAL SPECIFICATION", "SPECIFICATION",
    "DESIGN CRITERIA", "CRITERIA",
    "DESIGN REQUIREMENTS", "REQUIREMENTS",
    # Manuals
    "OPERATION & MAINTENANCE MANUAL", "ASSEMBLY MANUAL", "MANUAL",
    # Descriptions / Overviews
    "SYSTEM DESCRIPTION", "CONTROL DESCRIPTION", "CONTROL PHILOSOPHY",
    "OVERVIEW", "SUMMARY",
    # Lists / Schedules / Databases
    "INSTRUMENT LIST", "VALVE LIST", "CABLE SCHEDULE", "SCHEDULE",
    "LIST", "DATABASE",
    # Test / Procedure
    "TEST PROCEDURE", "TEST REPORT", "TEST",
    "PROCEDURE",
    # Reports / Studies
    "STUDY REPORT", "DESIGN REPORT", "HAZARDOUS AREA CLASSIFICATION",
    "REPORT", "STUDY",
    # Models / Curves
    "MODEL", "GENERATOR CAPABILITY CURVES AND DATA", "CAPABILITY CURVES AND DATA", "CAPABILITY CURVES",
    "PERFORMANCE DATA AND CURVES", "PERFORMANCE CURVES", "PERFORMANCE CURVE", "PERFORMANCE DATA",
    "CURVES", "CURVE",
    # Schematics
    "SCHEMATICS", "SCHEMATIC",
    # Notes / Plans
    "GENERAL NOTES", "NOTES",
    "PLAN",
    # Other
    "FOUNDATION AND LOADING DATA",
    "OPERATIONAL DATA",
    "SETTINGS",
    "ISOMETRIC",
    "ASSEMBLY",
    "OUTLINE",
    "SECTION",
    "DETAIL",
    "DIAGRAM",
    "DATA",
]


@dataclass(frozen=True)
class CanonicalDocumentCandidate:
    """Canonical MDL candidate dimensions used by candidate/rule/activity matching."""

    equipment: str
    system: str
    building: str
    deliverable_family: str
    deliverable_subtype: str
    scope_text: str


_DELIVERABLE_CANONICAL_PATTERNS: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "classification",
        "hazardous_area_classification",
        ("HAZARDOUS AREA CLASSIFICATION", "AREA CLASSIFICATION"),
    ),
    (
        "curve",
        "generator_capability_curve",
        ("GENERATOR CAPABILITY CURVES AND DATA", "CAPABILITY CURVES AND DATA", "CAPABILITY CURVES"),
    ),
    (
        "curve",
        "performance_curve",
        ("PERFORMANCE DATA AND CURVES", "PERFORMANCE CURVES", "PERFORMANCE CURVE", "PERFORMANCE DATA"),
    ),
    ("list", "io_list", ("I/O LIST", "IO LIST", "INPUT OUTPUT LIST", "INPUT / OUTPUT LIST")),
    ("list", "instrument_list", ("INSTRUMENT LIST", "LIST AND DATA SHEET FOR INSTRUMENT")),
    ("list", "equipment_list", ("EQUIPMENT LIST",)),
    ("list", "valve_list", ("VALVE LIST",)),
    ("list", "cable_schedule", ("CABLE SCHEDULE",)),
    ("schedule", "schedule", ("SCHEDULE",)),
    ("report", "cfd_report", ("CFD REPORT",)),
    ("report", "pre_fat_report", ("PRE FAT REPORT", "PRE-FAT REPORT")),
    ("report", "design_report", ("DESIGN REPORT",)),
    ("report", "study_report", ("STUDY REPORT",)),
    ("report", "test_report", ("TEST REPORT",)),
    ("report", "report", ("REPORT",)),
    ("specification", "painting_specification", ("PAINTING SPECIFICATION", "PAINT SPECIFICATION")),
    ("specification", "insulation_specification", ("INSULATION SPECIFICATION",)),
    ("specification", "fan_specification", ("FAN SPECIFICATION",)),
    ("specification", "drain_pump_specification", ("DRAIN PUMP SPECIFICATION", "CONDENSATE DRAIN PUMP SPECIFICATION")),
    ("specification", "scr_specification", ("SPECIFICATION FOR SCR", "TECHNICAL SPECIFICATION FOR SCR")),
    ("specification", "cable_specification", ("CABLE SPECIFICATION",)),
    ("specification", "gas_detector_specification", ("GAS DETECTOR SPECIFICATION",)),
    ("specification", "pump_specification", ("PUMP SPECIFICATION",)),
    ("specification", "technical_specification", ("TECHNICAL SPECIFICATIONS", "TECHNICAL SPECIFICATION")),
    ("specification", "specification", ("SPECIFICATION",)),
    ("datasheet", "technical_data_sheet", ("TECHNICAL DATA SHEET", "TECHNICAL DATASHEET")),
    ("datasheet", "data_sheet", ("DATA SHEET", "DATASHEET")),
    ("manual", "operation_maintenance_manual", ("OPERATION & MAINTENANCE MANUAL", "O&M MANUAL")),
    ("manual", "assembly_manual", ("ASSEMBLY MANUAL",)),
    ("manual", "manual", ("MANUAL",)),
    ("description", "system_description", ("SYSTEM DESCRIPTION",)),
    ("description", "control_description", ("CONTROL DESCRIPTION", "CONTROL PHILOSOPHY")),
    ("diagram", "p_id", ("P&I DIAGRAM", "P&ID", "PIPING AND INSTRUMENTATION DIAGRAM")),
    ("diagram", "single_line_diagram", ("SINGLE LINE DIAGRAM", "SLD")),
    ("diagram", "power_distribution_diagram", ("POWER DISTRIBUTION CONCEPT DIAGRAM", "POWER DISTRIBUTION DIAGRAM")),
    ("diagram", "hmi_graphic_diagram", ("HMI GRAPHIC DIAGRAM",)),
    ("diagram", "control_logic_diagram", ("ELECTRICAL CONTROL LOGIC DIAGRAM", "CONTROL LOGIC DIAGRAM")),
    ("diagram", "functional_loop_diagram", ("FUNCTIONAL LOOP DIAGRAM",)),
    ("diagram", "control_loop_diagram", ("CONTROL LOOP DIAGRAM", "CONTROL LOOP")),
    ("diagram", "wiring_diagram", ("WIRING DIAGRAM",)),
    ("diagram", "schematic_diagram", ("SCHEMATIC DIAGRAM", "SCHEMATICS", "SCHEMATIC")),
    ("diagram", "diagram", ("DIAGRAM",)),
    ("drawing", "general_arrangement_drawing", ("GENERAL ARRANGEMENT DRAWING", "GENERAL ARRANGEMENT", "GA DRAWING")),
    ("drawing", "layout_drawing", ("LAYOUT DRAWING", "LAYOUT")),
    ("drawing", "outline_drawing", ("OUTLINE DRAWING",)),
    ("drawing", "isometric_drawing", ("ISOMETRIC DRAWING", "ISOMETRIC")),
    ("drawing", "detail_drawing", ("DETAIL DRAWING", "DETAIL")),
    ("drawing", "sectional_drawing", ("SECTIONAL DRAWING", "SECTION")),
    ("drawing", "drawing", ("DRAWING",)),
    ("calculation", "sizing_calculation", ("SIZING CALCULATION",)),
    ("calculation", "design_calculation", ("DESIGN CALCULATION",)),
    ("calculation", "calculation", ("CALCULATION SHEET", "CALCULATION")),
    ("procedure", "test_procedure", ("TEST PROCEDURE",)),
    ("procedure", "procedure", ("PROCEDURE",)),
    ("criteria", "design_criteria", ("DESIGN CRITERIA", "CRITERIA")),
    ("requirements", "design_requirements", ("DESIGN REQUIREMENTS", "REQUIREMENTS")),
    ("plan", "plan", ("PLAN",)),
    ("notes", "general_notes", ("GENERAL NOTES", "NOTES")),
    ("model", "model", ("MODEL",)),
    ("data", "operational_data", ("OPERATIONAL DATA",)),
    ("data", "data", ("DATA",)),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_equipment(raw: str) -> str:
    """Normalize a raw equipment string (short code or full name) to canonical form."""
    cleaned = re.sub(r"\(.*?\)", "", raw).strip()
    upper = cleaned.upper()
    return _RAW_TO_CANONICAL.get(upper, cleaned) or raw.strip()


def canonicalize_mdl_candidate(
    *,
    title: str,
    equipment: str = "",
    system: str = "",
    building: str = "",
    deliverable: str = "",
) -> CanonicalDocumentCandidate:
    """Return canonical candidate fields for downstream constrained matching.

    The canonical deliverable family/subtype is intentionally deterministic. It
    distinguishes error-prone subtypes such as instrument list vs equipment list
    and design report vs CFD report before rule/activity matching consume the row.
    """
    canonical_equipment = normalize_equipment(equipment)
    if not canonical_equipment:
        canonical_equipment = extract_equipment_from_title(title)

    canonical_system = _canonical_text(system)
    canonical_building = _canonical_text(building)
    family, subtype = canonical_deliverable_type(deliverable=deliverable, title=title)
    scope_text = " | ".join(
        value for value in (canonical_equipment, canonical_system, canonical_building) if value
    )
    return CanonicalDocumentCandidate(
        equipment=canonical_equipment,
        system=canonical_system,
        building=canonical_building,
        deliverable_family=family,
        deliverable_subtype=subtype,
        scope_text=scope_text,
    )


def canonical_deliverable_type(*, deliverable: str = "", title: str = "") -> tuple[str, str]:
    """Classify raw MDL deliverable/title into stable family and subtype keys."""
    text = _canonical_match_text(deliverable, title)
    if not text:
        return "", ""
    for family, subtype, patterns in _DELIVERABLE_CANONICAL_PATTERNS:
        if any(_norm_for_match(pattern) in text for pattern in patterns):
            return family, subtype
    return "other", _slugify(normalize_deliverable(deliverable) or extract_deliverable(title) or title)


def _canonical_match_text(deliverable: str, title: str) -> str:
    parts = [
        deliverable,
        normalize_deliverable(deliverable),
        extract_deliverable(title),
        title,
    ]
    return _norm_for_match(" ".join(part for part in parts if part))


def _canonical_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _norm_for_match(value: str) -> str:
    value = value.upper().replace("&", " AND")
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _slugify(value: str) -> str:
    normalized = _norm_for_match(value)
    return re.sub(r"\s+", "_", normalized.lower()).strip("_")


def extract_equipment_from_title(title: str) -> str:
    """Scan a plain document title for known equipment keywords.

    Returns the canonical equipment name of the first match, or "" if none found.
    """
    upper = title.upper()
    for keyword, canonical in EQUIPMENT_SCAN:
        if keyword in upper:
            return canonical
    return ""


def normalize_deliverable(deliverable: str) -> str:
    """Map a raw MDL Deliverable value to the term used in validation_rule.csv keywords.

    Falls back to the trimmed input unchanged when no mapping is defined.
    """
    return _DELIVERABLE_TO_RULE_KEYWORD.get(deliverable.strip().upper(), deliverable.strip())


def refine_deliverable_with_title(deliverable: str, title: str) -> str:
    """Preserve specific deliverable families hidden behind a generic MDL value."""
    extracted = extract_deliverable(title)
    if not extracted:
        return deliverable.strip()

    current = deliverable.strip()
    current_upper = current.upper()
    if (
        (not current or current_upper in {"SPECIFICATION", "TECHNICAL SPECIFICATION", "TECHNICAL SPECIFICATIONS"})
        and extracted in {"PAINTING SPECIFICATION", "PAINT SPECIFICATION"}
    ):
        return extracted
    if current_upper in {"", "DATA", "OPERATIONAL DATA", "PERFORMANCE DATA", "CURVES", "CURVE"} and extracted in {
        "GENERATOR CAPABILITY CURVES AND DATA",
        "CAPABILITY CURVES AND DATA",
        "CAPABILITY CURVES",
        "PERFORMANCE DATA AND CURVES",
        "PERFORMANCE CURVES",
        "PERFORMANCE CURVE",
        "PERFORMANCE DATA",
        "CURVES",
        "CURVE",
    }:
        return extracted
    return current


def extract_deliverable(text: str) -> str:
    """Scan raw document text for a known deliverable-type keyword.

    Returns the first (longest/most specific) matching keyword, or "" if none found.
    Applied to both the parsed title and any equipment prefix that may itself be a
    document type masquerading as equipment.
    """
    upper = text.upper()
    for keyword in _DELIVERABLE_SCAN_KEYWORDS:
        if keyword in upper:
            return keyword
    return ""


def equipment_to_abbr(canonical: str) -> str:
    """Return the abbreviation used in validation_rule.csv for a canonical equipment name.

    Falls back to the input unchanged when no mapping is defined.
    """
    return CANONICAL_TO_ABBR.get(canonical, canonical)


def expand_query_tokens(tokens: set[str]) -> frozenset[str]:
    """Inject equipment abbreviations when all full-name tokens are present in the query.

    Example: {"heat", "recovery", "steam", "generator"} ⊆ tokens → adds "hrsg".
    This lets a title like "Heat Recovery Steam Generator General Arrangement" reach
    the same HRSG-specific validation rules as a query already containing "hrsg".
    """
    extra: set[str] = set()
    for full_tokens, abbr in FULL_NAME_TO_ABBR_TOKENS:
        if full_tokens <= tokens:
            extra.add(abbr)
    if extra:
        return frozenset(tokens | extra)
    return frozenset(tokens)
