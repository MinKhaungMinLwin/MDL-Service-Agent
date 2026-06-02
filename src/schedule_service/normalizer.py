"""Central equipment name normalizer for CCPP schedule service.

Single source of truth for all equipment name mappings used across:
- candidate_extractor: raw Matched_Doc_N strings → canonical name
- schedule_generator: canonical name → abbreviation (rule_query construction)
- rule_loader: full-name tokens → abbreviation (query token expansion)

Changing a mapping here propagates to all three consumers automatically.
"""

from __future__ import annotations

import re

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
# Public API
# ---------------------------------------------------------------------------

def normalize_equipment(raw: str) -> str:
    """Normalize a raw equipment string (short code or full name) to canonical form."""
    cleaned = re.sub(r"\(.*?\)", "", raw).strip()
    upper = cleaned.upper()
    return _RAW_TO_CANONICAL.get(upper, cleaned) or raw.strip()


def extract_equipment_from_title(title: str) -> str:
    """Scan a plain document title for known equipment keywords.

    Returns the canonical equipment name of the first match, or "" if none found.
    """
    upper = title.upper()
    for keyword, canonical in EQUIPMENT_SCAN:
        if keyword in upper:
            return canonical
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
