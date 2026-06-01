"""Extract MDL document candidates from ITB matching CSV output.

Reads an ITB matching CSV (output_match_*.csv) that contains Matched_Doc_1..N
columns, parses each matched document name into structured fields, filters by
score threshold, deduplicates, and writes an MDL candidate CSV compatible with
the *_MDL_classified.csv format so it can be fed into /schedule/generate.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from loguru import logger

DEFAULT_SCORE_THRESHOLD = 0.85
DEFAULT_TOP_N = 5          # how many Matched_Doc_N per row to consider
DEFAULT_OUTPUT_DIR = Path("output/schedule_service")

# Known deliverable keywords to extract from title (longest/most specific first)
_DELIVERABLE_KEYWORDS: list[str] = [
    # P&ID variants
    "P&I DIAGRAM", "P&ID", "PIPING AND INSTRUMENTATION DIAGRAM",
    # Arrangement / Layout
    "GENERAL ARRANGEMENT", "GA DRAWING",
    "ARRANGEMENT DRAWING", "ARRANGEMENT",
    "LAYOUT DRAWING", "LAYOUT",
    # Electrical diagrams
    "SINGLE LINE DIAGRAM",
    # Calculation
    "CALCULATION SHEET", "CALCULATION",
    # Data sheet
    "DATA SHEET",
    # Drawings
    "OUTLINE DRAWING", "ISOMETRIC DRAWING", "DETAIL DRAWING", "ELEVATION",
    "DRAWING",
    # Specification / Criteria / Requirements
    "TECHNICAL SPECIFICATION", "SPECIFICATION",
    "DESIGN CRITERIA", "CRITERIA",
    "DESIGN REQUIREMENTS", "REQUIREMENTS",
    # Descriptions / Overviews
    "SYSTEM DESCRIPTION", "CONTROL DESCRIPTION", "CONTROL PHILOSOPHY",
    "OVERVIEW", "SUMMARY",
    # Lists / Schedules / Databases
    "INSTRUMENT LIST", "CABLE SCHEDULE", "SCHEDULE",
    "LIST", "DATABASE",
    # Test / Procedure
    "TEST PROCEDURE", "TEST REPORT", "TEST",
    "PROCEDURE",
    # Reports / Studies
    "STUDY REPORT", "DESIGN REPORT", "HAZARDOUS AREA CLASSIFICATION",
    "REPORT", "STUDY",
    # Models / Curves
    "MODEL", "CURVES", "CURVE",
    # Schematics
    "SCHEMATICS", "SCHEMATIC",
    # Notes
    "GENERAL NOTES", "NOTES",
    # Other
    "FOUNDATION AND LOADING DATA",
    "PERFORMANCE CURVE", "PERFORMANCE DATA",
    "OPERATIONAL DATA", "DATA",
    "SETTINGS",
    "ISOMETRIC",
    "DETAIL",
    "DIAGRAM",
]

# Normalize equipment abbreviations to full names
_EQUIPMENT_NORM: dict[str, str] = {
    "GTG": "Gas Turbine Generator",
    "GT": "Gas Turbine Generator",
    "HRSG": "Heat Recovery Steam Generator",
    "STG": "Steam Turbine & Generator",
    "ST": "Steam Turbine",
    "ACC": "Air Cooled Condenser",
    "BOP": "Balance of Plant",
    "DCS": "DCS",
    "BOP PIPING": "BOP Piping",
    "CCWP": "Cooling Water Package",
    "FGP": "Fuel Gas Package",
    "BSEDG": "Blackstart Emergency Diesel Generator",
}


def extract_candidates(
    input_csv: Path,
    output_dir: Path,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    top_n: int = DEFAULT_TOP_N,
    limit: int = 0,
) -> Path:
    """Extract and deduplicate MDL candidates from an ITB matching CSV.

    Returns the path to the written candidate CSV.
    """
    logger.info("Reading ITB matching CSV: {}", input_csv)
    rows = _read_csv(input_csv)
    original_count = len(rows)
    if limit > 0:
        rows = rows[:limit]
        logger.info("Limit: processing first {} of {} rows", len(rows), original_count)

    candidates: dict[str, dict[str, Any]] = {}  # dedup_key → candidate

    for row in rows:
        itb_doc = row.get("Document", "").strip()
        itb_page = row.get("Page", "").strip()

        for i in range(1, top_n + 1):
            raw = row.get(f"Matched_Doc_{i}", "").strip()
            if not raw:
                continue
            parsed = _parse_matched_doc(raw)
            if parsed["score"] < score_threshold:
                continue

            key = _dedup_key(parsed["equipment"], parsed["deliverable"], parsed["title"])
            if key not in candidates:
                candidates[key] = {
                    **parsed,
                    "itb_sources": [],
                }
            candidates[key]["itb_sources"].append(
                f"{itb_doc}:p{itb_page}(score={parsed['score']:.2f})"
            )
            # Keep highest score
            if parsed["score"] > candidates[key]["score"]:
                candidates[key]["score"] = parsed["score"]

    candidate_list = sorted(candidates.values(), key=lambda c: c["score"], reverse=True)
    logger.info(
        "Extracted {} unique MDL candidates (threshold={}, top_n={})",
        len(candidate_list), score_threshold, top_n,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"mdl_candidates_{input_csv.stem}"
    output_path = output_dir / f"{stem}.csv"
    _write_csv(output_path, candidate_list)
    logger.info("Wrote MDL candidates to {}", output_path)
    return output_path


def _parse_matched_doc(raw: str) -> dict[str, Any]:
    """Parse one Matched_Doc_N string into structured fields."""
    score = _extract_score(raw)

    # Strip score suffix
    text = re.sub(r"\s*\([^)]*(?:CrossEncoder|Vector|BM25|Semantic|RRF|최종점수)[^)]*\)\s*$", "", raw).strip()

    # Strip [Project] prefix
    text = re.sub(r'^\[.+?\]\s*', '', text)

    # Optional [Equipment bracket]
    equip_bracket = ""
    m_eq = re.match(r'^\[(.+?)\]\s*', text)
    if m_eq:
        equip_bracket = re.sub(r'\(.*?\)', '', m_eq.group(1)).strip()  # strip "(For Block 2)"
        text = text[m_eq.end():]

    # Parse remaining text into equipment + title
    # Pattern 1: "EQUIPMENT - REST OF TITLE"
    if ' - ' in text:
        parts = text.split(' - ', 1)
        raw_equipment = equip_bracket or parts[0].strip()
        title = parts[1].strip()
    # Pattern 2: "EQUIP_CODE_TITLE" (short code before first underscore)
    elif '_' in text:
        parts = text.split('_', 1)
        if len(parts[0]) <= 12:
            raw_equipment = equip_bracket or parts[0].strip()
            title = parts[1].replace('_', ' ').strip()
        else:
            raw_equipment = equip_bracket
            title = text.replace('_', ' ').strip()
    else:
        raw_equipment = equip_bracket
        title = text

    equipment = _normalize_equipment(raw_equipment)
    deliverable = _extract_deliverable(title)

    return {
        "project": "",        # stripped above
        "equipment": equipment,
        "title": title,
        "deliverable": deliverable,
        "score": score,
    }


def _extract_score(raw: str) -> float:
    """Extract the best available matching score from a formatted candidate."""
    for pattern in (
        r"CrossEncoder:\s*([-+]?\d*\.?\d+)",
        r"Vector:\s*([-+]?\d*\.?\d+)",
        r"최종점수:\s*([-+]?\d*\.?\d+)",
    ):
        match = re.search(pattern, raw)
        if match:
            return float(match.group(1))
    return 0.0


def _extract_deliverable(title: str) -> str:
    """Extract deliverable type from a document title."""
    title_upper = title.upper()
    for kw in _DELIVERABLE_KEYWORDS:
        if kw in title_upper:
            return kw
    return ""


def _normalize_equipment(raw: str) -> str:
    """Normalize equipment abbreviation to full name."""
    upper = raw.strip().upper()
    return _EQUIPMENT_NORM.get(upper, raw.strip())


def _dedup_key(equipment: str, deliverable: str, title: str) -> str:
    """Build a deduplication key from equipment + deliverable + normalized title."""
    norm_title = re.sub(r'\s+', ' ', title.upper().strip())
    norm_eq = equipment.upper().strip()
    norm_del = deliverable.upper().strip()
    return f"{norm_eq}|{norm_del}|{norm_title}"


def _write_csv(path: Path, candidates: list[dict[str, Any]]) -> None:
    """Write candidate list as CSV compatible with *_MDL_classified.csv format."""
    fieldnames = [
        # MDL_classified.csv compatible columns
        "Source File",
        "Document No",
        "Title",
        "Equipment",
        "Building",
        "System",
        "Deliverable",
        "Note",
        # Traceability columns
        "match_score",
        "itb_sources",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in candidates:
            writer.writerow({
                "Source File": "itb_candidates",
                "Document No": "",
                "Title": c["title"],
                "Equipment": c["equipment"],
                "Building": "",
                "System": "",
                "Deliverable": c["deliverable"],
                "Note": "",
                "match_score": f"{c['score']:.4f}",
                "itb_sources": " | ".join(c["itb_sources"][:5]),
            })


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
