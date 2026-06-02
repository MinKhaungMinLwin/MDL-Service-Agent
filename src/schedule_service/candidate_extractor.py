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

from schedule_service.normalizer import (
    extract_equipment_from_title as _extract_equipment_from_title_fn,
)
from schedule_service.normalizer import (
    normalize_equipment as _normalize_equipment_fn,
)

DEFAULT_SCORE_THRESHOLD = 0.75
DEFAULT_TOP_N = 5          # how many Matched_Doc_N per row to consider
DEFAULT_OUTPUT_DIR = Path("output/schedule_service")

# Known deliverable keywords to extract from title (longest/most specific first)
_DELIVERABLE_KEYWORDS: list[str] = [
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
    "MODEL", "PERFORMANCE CURVE", "PERFORMANCE DATA", "CURVES", "CURVE",
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



def extract_candidates(
    input_csv: Path,
    output_dir: Path,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    top_n: int = DEFAULT_TOP_N,
    limit: int = 0,
    classify_with_llm: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Extract and deduplicate MDL candidates from an ITB matching CSV.

    Returns (csv_path, timing) where timing breaks down each processing phase.
    """
    import time

    t0 = time.perf_counter()

    logger.info("Reading ITB matching CSV: {}", input_csv)
    rows = _read_csv(input_csv)
    original_count = len(rows)
    if limit > 0:
        rows = rows[:limit]
        logger.info("Limit: processing first {} of {} rows", len(rows), original_count)

    t_read = time.perf_counter()

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
    t_regex = time.perf_counter()

    logger.info(
        "Extracted {} unique MDL candidates (threshold={}, top_n={})",
        len(candidate_list), score_threshold, top_n,
    )

    llm_timing: dict[str, Any] = {"llm_enabled": False}
    if classify_with_llm and candidate_list:
        logger.info(
            "LLM-classifying {} candidates to improve Equipment/Building/System/Deliverable fields",
            len(candidate_list),
        )
        llm_timing = _classify_candidates(candidate_list)

    t_llm = time.perf_counter()

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"mdl_candidates_{input_csv.stem}"
    output_path = output_dir / f"{stem}.csv"
    _write_csv(output_path, candidate_list)

    t_end = time.perf_counter()

    timing: dict[str, Any] = {
        "csv_read_s": round(t_read - t0, 3),
        "regex_extract_s": round(t_regex - t_read, 3),
        "llm_total_s": round(t_llm - t_regex, 3),
        "write_s": round(t_end - t_llm, 3),
        "total_s": round(t_end - t0, 3),
        "candidates_total": len(candidate_list),
        **llm_timing,
    }
    logger.info(
        "Timing — read: {csv_read_s}s | regex: {regex_extract_s}s"
        " | llm: {llm_total_s}s | write: {write_s}s | total: {total_s}s",
        **timing,
    )
    logger.info("Wrote MDL candidates to {}", output_path)
    return output_path, timing


def _parse_matched_doc(raw: str) -> dict[str, Any]:
    """Parse one Matched_Doc_N string into structured fields."""
    score = _extract_score(raw)

    # Strip score suffix
    text = re.sub(r"\s*\([^)]*(?:CrossEncoder|Vector|BM25|Semantic|RRF|최종점수)[^)]*\)\s*$", "", raw).strip()

    # Strip [Project] prefix
    text = re.sub(r'^\[.+?\]\s*', '', text)

    document_no = ""
    m_doc = re.match(r'^([A-Za-z0-9][A-Za-z0-9_.\/-]*\d[A-Za-z0-9_.\/-]*)\s+-\s+(.+)$', text)
    if m_doc:
        document_no = m_doc.group(1).strip()
        text = m_doc.group(2).strip()

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
    # Pattern 2: "EQUIPMENT_TITLE" — extract equipment from prefix, keep full text as title
    elif '_' in text:
        parts = text.split('_', 1)
        raw_equipment = equip_bracket or parts[0].strip()
        title = text.replace('_', ' ').strip()
    else:
        # No separator — scan title text for known equipment keywords
        raw_equipment = equip_bracket
        title = text

    # If the extracted prefix is itself a deliverable keyword (e.g. "CONTROL LOGIC DIAGRAM_FUEL OIL...")
    # it is a doc type masquerading as equipment — drop it and scan the title instead.
    forced_deliverable = ""
    if raw_equipment and not equip_bracket:
        extracted = _extract_deliverable(raw_equipment)
        if extracted:
            forced_deliverable = extracted
            raw_equipment = ""

    equipment = _normalize_equipment(raw_equipment)
    if not equipment:
        equipment = _extract_equipment_from_title(title)
    deliverable = _extract_deliverable(title) or forced_deliverable

    return {
        "project": "",        # stripped above
        "document_no": document_no,
        "equipment": equipment,
        "building": "",
        "system": "",
        "title": title,
        "deliverable": deliverable,
        "score": score,
    }


def _extract_score(raw: str) -> float:
    """Extract the best available matching score from a formatted candidate.

    Score format evolution:
    - New format (hybrid/semantic mode): Semantic score (0–1 cosine similarity) is
      the reliable 0–1 range metric. CrossEncoder in this format is an ms-marco raw
      logit (can be negative) and is NOT comparable to the 0–1 threshold.
    - Old format (Korean pipeline): 최종점수 is a combined score, often > 1.
    Priority: Semantic → 최종점수/Vector (old) → CrossEncoder only if positive.
    """
    # Prefer Semantic (0–1 range, comparable to score_threshold)
    m = re.search(r"Semantic:\s*([-+]?\d*\.?\d+)", raw)
    if m:
        return float(m.group(1))
    # Old-format combined scores
    for pattern in (r"최종점수:\s*([-+]?\d*\.?\d+)", r"Vector:\s*([-+]?\d*\.?\d+)"):
        m = re.search(pattern, raw)
        if m:
            return float(m.group(1))
    # CrossEncoder as last resort — only use if positive (ms-marco logit scale)
    m = re.search(r"CrossEncoder:\s*([-+]?\d*\.?\d+)", raw)
    if m:
        val = float(m.group(1))
        return val if val > 0 else 0.0
    return 0.0


def _extract_deliverable(title: str) -> str:
    """Extract deliverable type from a document title."""
    title_upper = title.upper()
    for kw in _DELIVERABLE_KEYWORDS:
        if kw in title_upper:
            return kw
    return ""


def _normalize_equipment(raw: str) -> str:
    """Normalize equipment name to canonical form."""
    return _normalize_equipment_fn(raw)


def _extract_equipment_from_title(title: str) -> str:
    """Scan a plain title (no separator) for known equipment keywords."""
    return _extract_equipment_from_title_fn(title)


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
                "Document No": c.get("document_no", ""),
                "Title": c["title"],
                "Equipment": c["equipment"],
                "Building": c.get("building", ""),
                "System": c.get("system", ""),
                "Deliverable": c["deliverable"],
                "Note": "",
                "match_score": f"{c['score']:.4f}",
                "itb_sources": " | ".join(c["itb_sources"][:5]),
            })


def _classify_candidates(
    candidates: list[dict[str, Any]], batch_size: int = 20, max_workers: int = 4
) -> dict[str, Any]:
    """Re-classify Equipment/Building/System/Deliverable using the MDL LLM classifier.

    Only sends candidates where equipment or deliverable is missing after regex extraction.
    Batches are processed in parallel. Mutates candidates in-place and returns timing info.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from common.config import required_env
    from common.openai_client import build_azure_openai_client
    from mdl_service.classification import DEFAULT_CLASSIFICATION_PROMPT_PATH, MDLClassifier, load_system_prompt

    t_import = time.perf_counter()

    # Skip candidates where regex already extracted both fields
    need_llm = [c for c in candidates if not c.get("equipment") or not c.get("deliverable")]
    skipped = len(candidates) - len(need_llm)
    if skipped:
        logger.info("LLM classify: skipping {} candidates already fully extracted by regex", skipped)

    timing: dict[str, Any] = {
        "llm_enabled": True,
        "llm_import_s": 0.0,
        "llm_classify_s": 0.0,
        "llm_candidates_skipped": skipped,
        "llm_candidates_sent": len(need_llm),
        "llm_batches": 0,
    }

    if not need_llm:
        return timing

    client = build_azure_openai_client("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    model = required_env("AZURE_OPENAI_CHAT_DEPLOYMENT")
    system_prompt = load_system_prompt(DEFAULT_CLASSIFICATION_PROMPT_PATH)

    t_classify = time.perf_counter()
    timing["llm_import_s"] = round(t_classify - t_import, 3)

    batches = [need_llm[i : i + batch_size] for i in range(0, len(need_llm), batch_size)]
    timing["llm_batches"] = len(batches)
    logger.info(
        "LLM classifying {} candidates in {} batches (parallel workers={})",
        len(need_llm), len(batches), min(max_workers, len(batches)),
    )

    def _run_batch(batch_idx: int, batch: list[dict[str, Any]]) -> tuple[int, list]:
        classifier = MDLClassifier(client, model, system_prompt)
        titles = [c["title"] for c in batch]
        logger.info("LLM batch {}/{} started ({} titles)", batch_idx + 1, len(batches), len(titles))
        results = classifier.classify_titles(titles)
        logger.info("LLM batch {}/{} done", batch_idx + 1, len(batches))
        return batch_idx, results

    with ThreadPoolExecutor(max_workers=min(max_workers, len(batches))) as executor:
        futures = {executor.submit(_run_batch, i, batch): batch for i, batch in enumerate(batches)}
        for future in as_completed(futures):
            batch = futures[future]
            _, results = future.result()
            for candidate, result in zip(batch, results, strict=True):
                if result.equipment:
                    candidate["equipment"] = result.equipment
                if result.building:
                    candidate["building"] = result.building
                if result.system:
                    candidate["system"] = result.system
                if result.deliverable:
                    candidate["deliverable"] = result.deliverable

    timing["llm_classify_s"] = round(time.perf_counter() - t_classify, 3)
    return timing


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
