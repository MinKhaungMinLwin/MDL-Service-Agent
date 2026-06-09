"""Extract MDL document candidates from ITB matching CSV output.

Reads an ITB matching CSV (output_match_*.csv) that contains Matched_Doc_1..N
columns, parses each matched document name into structured fields, filters by
score threshold, deduplicates, and writes an MDL candidate CSV compatible with
the *_MDL_classified.csv format so it can be fed into /schedule/generate.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

from schedule_service.normalizer import (
    extract_deliverable as _extract_deliverable_fn,
)
from schedule_service.normalizer import (
    extract_equipment_from_title as _extract_equipment_from_title_fn,
)
from schedule_service.normalizer import (
    normalize_equipment as _normalize_equipment_fn,
)
from schedule_service.normalizer import refine_deliverable_with_title

DEFAULT_SCORE_THRESHOLD = 0.70
DEFAULT_TOP_N = 20         # how many Matched_Doc_N per row to consider
DEFAULT_SELECTION_TOP_PER_CHUNK = 10
DEFAULT_SELECTION_HIGH_SCORE = 0.82
DEFAULT_OUTPUT_DIR = Path("output/schedule_service/candidates")


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

    logger.info("Reading ITB matching output: {}", input_csv)
    is_json = input_csv.suffix.lower() == ".json"
    rows = _read_matching_json(input_csv) if is_json else _read_csv(input_csv)
    original_count = len(rows)
    if limit > 0:
        rows = rows[:limit]
        logger.info("Limit: processing first {} of {} rows", len(rows), original_count)

    t_read = time.perf_counter()

    candidate_list = (
        _extract_candidates_from_json_records(rows, score_threshold, top_n)
        if is_json
        else _extract_candidates_from_csv_rows(rows, score_threshold, top_n)
    )
    t_regex = time.perf_counter()

    logger.info(
        "Extracted {} unique MDL candidates (threshold={}, top_n={})",
        len(candidate_list), score_threshold, top_n,
    )
    _select_final_candidates(candidate_list)

    llm_timing: dict[str, Any] = {"llm_enabled": False}
    if classify_with_llm and candidate_list:
        logger.info(
            "LLM-classifying {} candidates to improve Equipment/Building/System/Deliverable fields",
            len(candidate_list),
        )
        llm_timing = _classify_candidates(candidate_list)
        _refresh_candidate_quality(candidate_list)
        _select_final_candidates(candidate_list)

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


def _extract_candidates_from_csv_rows(
    rows: list[dict[str, str]],
    score_threshold: float,
    top_n: int,
) -> list[dict[str, Any]]:
    """Extract candidates from the legacy display CSV format."""
    candidates: dict[str, dict[str, Any]] = {}

    for row in rows:
        itb_doc = row.get("Document", "").strip()
        itb_page = row.get("Page", "").strip()
        chunk_id = row.get("Chunk ID", "").strip()

        for i in range(1, top_n + 1):
            raw = row.get(f"Matched_Doc_{i}", "").strip()
            if not raw:
                continue
            parsed = _parse_matched_doc(raw)
            if parsed["score"] < score_threshold:
                continue

            parsed["rank"] = i
            parsed["candidate_status"], parsed["quality_issues"] = _candidate_quality(parsed)
            key = _dedup_key(parsed["equipment"], parsed["deliverable"], parsed["title"])
            _upsert_candidate(candidates, key, parsed, itb_doc, itb_page, chunk_id)

    return sorted(candidates.values(), key=lambda c: c["score"], reverse=True)


def _extract_candidates_from_json_records(
    records: list[dict[str, Any]],
    score_threshold: float,
    top_n: int,
) -> list[dict[str, Any]]:
    """Extract candidates from structured matching JSON records."""
    candidates: dict[str, dict[str, Any]] = {}

    for record in records:
        itb_doc = str(record.get("document", "") or "").strip()
        itb_page = str(record.get("page", "") or "").strip()
        chunk_id = str(record.get("chunk_id", "") or "").strip()
        requirement_intent = record.get("requirement_intent", {})

        for candidate in record.get("candidates", [])[:top_n]:
            parsed = _candidate_from_json(candidate)
            _apply_requirement_intent(parsed, requirement_intent)
            if parsed["score"] < score_threshold:
                continue
            parsed["candidate_status"], parsed["quality_issues"] = _candidate_quality(parsed)
            key = _structured_dedup_key(parsed)
            _upsert_candidate(candidates, key, parsed, itb_doc, itb_page, chunk_id)

    return sorted(candidates.values(), key=lambda c: c["score"], reverse=True)


def _candidate_from_json(candidate: dict[str, Any]) -> dict[str, Any]:
    """Normalize one structured JSON candidate into the schedule-candidate shape."""
    title = _as_text(candidate.get("title"))
    deliverable = refine_deliverable_with_title(
        _as_text(candidate.get("deliverable")) or _extract_deliverable(title),
        title,
    )
    equipment = _normalize_equipment(_as_text(candidate.get("equipment")))
    if not equipment:
        equipment = _extract_equipment_from_title(title)
    return {
        "project": "",
        "doc_id": _as_text(candidate.get("doc_id")),
        "source_file": _as_text(candidate.get("source_file")),
        "document_no": _as_text(candidate.get("document_no")),
        "equipment": equipment,
        "building": _as_text(candidate.get("building")),
        "system": _as_text(candidate.get("system")),
        "title": title,
        "deliverable": deliverable,
        "score": _candidate_score(candidate),
        "semantic_score": candidate.get("semantic_score"),
        "cross_encoder_score": candidate.get("cross_encoder_score"),
        "rrf_score": candidate.get("rrf_score"),
        "rank": candidate.get("rank") or candidate.get("final_rank"),
        "retrieval_rank": candidate.get("retrieval_rank"),
        "parse_source": "json_metadata",
    }


def _select_final_candidates(
    candidates: list[dict[str, Any]],
    top_per_chunk: int = DEFAULT_SELECTION_TOP_PER_CHUNK,
    high_score_threshold: float = DEFAULT_SELECTION_HIGH_SCORE,
) -> None:
    """Mark the final candidates to feed into schedule generation while keeping backups for audit."""
    selected: set[int] = set()
    reasons: dict[int, set[str]] = {idx: set() for idx in range(len(candidates))}
    chunk_candidates: dict[str, list[tuple[int, float, int]]] = {}
    for idx, candidate in enumerate(candidates):
        for chunk_id, rank in _candidate_chunk_ranks(candidate).items():
            chunk_candidates.setdefault(chunk_id, []).append((rank, -float(candidate.get("score") or 0.0), idx))
        if float(candidate.get("score") or 0.0) >= high_score_threshold:
            selected.add(idx)
            reasons[idx].add(f"high_score>={high_score_threshold:.2f}")

    best_selected_rank: dict[int, int] = {}
    for chunk_id, items in chunk_candidates.items():
        items.sort()
        for rank, _score_sort, idx in items[:top_per_chunk]:
            selected.add(idx)
            reasons[idx].add(f"top_{top_per_chunk}:{chunk_id}")
            best_selected_rank[idx] = min(best_selected_rank.get(idx, rank), rank)

    for idx, candidate in enumerate(candidates):
        chunk_ranks = _candidate_chunk_ranks(candidate)
        candidate["candidate_selection_status"] = "selected" if idx in selected else "backup"
        candidate["candidate_selection_rank"] = best_selected_rank.get(idx, min(chunk_ranks.values() or [0])) or ""
        candidate["candidate_selection_score"] = _candidate_selection_score(candidate)
        candidate["candidate_selection_reasons"] = (
            ";".join(sorted(reasons[idx])) if idx in selected else "outside_top_k"
        )


def _candidate_chunk_ranks(candidate: dict[str, Any]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for source in candidate.get("itb_sources", []):
        for chunk_id in re.findall(r"[A-Za-z0-9_.&-]+_chunk_\d+", source):
            rank_match = re.search(r"rank=(\d+)", source)
            rank = int(rank_match.group(1)) if rank_match else int(candidate.get("rank") or 999)
            ranks[chunk_id] = min(ranks.get(chunk_id, rank), rank)
    return ranks


def _candidate_selection_score(candidate: dict[str, Any]) -> float:
    score = float(candidate.get("score") or 0.0)
    best_rank = min(_candidate_chunk_ranks(candidate).values() or [99])
    rank_bonus = max(0, DEFAULT_TOP_N + 1 - best_rank) * 0.003
    completeness_bonus = 0.0
    if candidate.get("deliverable", "").strip():
        completeness_bonus += 0.015
    if any(candidate.get(field, "").strip() for field in ("equipment", "system", "building")):
        completeness_bonus += 0.015
    if candidate.get("candidate_status") == "accepted":
        completeness_bonus += 0.010
    return score + rank_bonus + completeness_bonus


def _candidate_score(candidate: dict[str, Any]) -> float:
    """Return the filtering/sorting score for structured JSON candidates."""
    value = candidate.get("semantic_score")
    if value is None:
        value = candidate.get("rrf_score")
    if value is None:
        value = candidate.get("cross_encoder_score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _upsert_candidate(
    candidates: dict[str, dict[str, Any]],
    key: str,
    parsed: dict[str, Any],
    itb_doc: str,
    itb_page: str,
    chunk_id: str = "",
) -> None:
    if key not in candidates:
        candidates[key] = {
            **parsed,
            "itb_sources": [],
            "requirement_intent_equipment": [],
            "requirement_intent_systems": [],
            "requirement_intent_deliverables": [],
            "requirement_intent_actions": [],
            "requirement_intent_constraints": [],
        }
    _merge_requirement_intent(candidates[key], parsed)
    candidates[key]["itb_sources"].append(_itb_source(itb_doc, itb_page, chunk_id, parsed))
    if parsed["score"] > candidates[key]["score"]:
        previous_sources = candidates[key]["itb_sources"]
        previous_intent = _candidate_intent_lists(candidates[key])
        candidates[key].update(parsed)
        candidates[key]["itb_sources"] = previous_sources
        for field, values in previous_intent.items():
            candidates[key][field] = _unique_texts([*values, *parsed.get(field, [])])


def _itb_source(itb_doc: str, itb_page: str, chunk_id: str, parsed: dict[str, Any]) -> str:
    page = f":p{itb_page}" if itb_page else ""
    chunk = f":{chunk_id}" if chunk_id else ""
    rank = parsed.get("rank")
    rank_part = f",rank={rank}" if rank else ""
    return f"{itb_doc}{page}{chunk}(score={parsed['score']:.2f}{rank_part})"


def _apply_requirement_intent(candidate: dict[str, Any], requirement_intent: Any) -> None:
    if not isinstance(requirement_intent, dict):
        requirement_intent = {}
    candidate["requirement_intent_equipment"] = _intent_values(requirement_intent, "equipment")
    candidate["requirement_intent_systems"] = _intent_values(requirement_intent, "systems")
    candidate["requirement_intent_deliverables"] = _intent_values(requirement_intent, "deliverables")
    candidate["requirement_intent_actions"] = _intent_values(requirement_intent, "actions")
    candidate["requirement_intent_constraints"] = _intent_values(requirement_intent, "constraints")


def _merge_requirement_intent(target: dict[str, Any], source: dict[str, Any]) -> None:
    for field in _candidate_intent_lists(target):
        target[field] = _unique_texts([*target.get(field, []), *source.get(field, [])])


def _candidate_intent_lists(candidate: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "requirement_intent_equipment": list(candidate.get("requirement_intent_equipment", [])),
        "requirement_intent_systems": list(candidate.get("requirement_intent_systems", [])),
        "requirement_intent_deliverables": list(candidate.get("requirement_intent_deliverables", [])),
        "requirement_intent_actions": list(candidate.get("requirement_intent_actions", [])),
        "requirement_intent_constraints": list(candidate.get("requirement_intent_constraints", [])),
    }


def _intent_values(requirement_intent: dict[str, Any], key: str) -> list[str]:
    values = requirement_intent.get(key, [])
    if not isinstance(values, list):
        return []
    return _unique_texts(values)


def _unique_texts(values: list[Any]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


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
        "doc_id": "",
        "source_file": "",
        "document_no": document_no,
        "equipment": equipment,
        "building": "",
        "system": "",
        "title": title,
        "deliverable": deliverable,
        "score": score,
        "semantic_score": "",
        "cross_encoder_score": "",
        "rrf_score": "",
        "rank": "",
        "retrieval_rank": "",
        "parse_source": "csv_display",
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
    return _extract_deliverable_fn(title)


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


def _structured_dedup_key(candidate: dict[str, Any]) -> str:
    """Prefer stable MDL identity over parsed text keys."""
    doc_id = candidate.get("doc_id", "").strip()
    if doc_id:
        return f"doc_id:{doc_id}"
    source_file = candidate.get("source_file", "").strip()
    document_no = candidate.get("document_no", "").strip()
    if source_file and document_no:
        return f"source_doc:{source_file}|{document_no}"
    if source_file and candidate.get("title", "").strip():
        return f"source_title:{source_file}|{_norm(candidate['title'])}"
    return _dedup_key(candidate["equipment"], candidate["deliverable"], candidate["title"])


def _candidate_quality(candidate: dict[str, Any]) -> tuple[str, str]:
    """Return candidate_status and a semicolon-separated quality issue list."""
    issues = []
    scope = " ".join(
        value for value in [candidate.get("equipment", ""), candidate.get("system", ""), candidate.get("building", "")]
        if value
    )
    if not candidate.get("title", "").strip():
        issues.append("missing_title")
    if not scope.strip() and not _is_global_scope_candidate(candidate):
        issues.append("missing_scope")
    if not candidate.get("deliverable", "").strip():
        issues.append("missing_deliverable")
    if _looks_like_document_code(candidate.get("equipment", "")):
        issues.append("equipment_looks_like_document_code")
    status = "accepted" if not issues else "needs_review"
    return status, ";".join(issues)


def _is_global_scope_candidate(candidate: dict[str, Any]) -> bool:
    """Return True when a candidate is intentionally plant-level instead of scoped to equipment/system/building."""
    title = _norm(candidate.get("title", ""))
    deliverable = _norm(candidate.get("deliverable", ""))
    text = f"{title} {deliverable}"
    if not title or not deliverable:
        return False

    global_title_patterns = (
        "PLANT OVERALL",
        "PLANT PERFORMANCE",
        "PLANT GENERAL",
        "OVERALL PLANT",
        "OVERALL PROTECTION",
        "OVERALL SYSTEM",
        "SITE",
    )
    if any(pattern in text for pattern in global_title_patterns):
        return True

    global_deliverable_patterns = (
        "HAZARDOUS AREA CLASSIFICATION",
        "AREA CLASSIFICATION",
        "PERFORMANCE CORRECTION CURVE",
        "PERFORMANCE CURVE",
        "CAPABILITY CURVE",
        "CORRECTION CURVE",
    )
    if any(pattern in text for pattern in global_deliverable_patterns):
        return True

    if "CLASSIFICATION" in deliverable and any(pattern in title for pattern in ("PLANT", "OVERALL", "SITE")):
        return True
    return "CURVE" in deliverable and any(
        pattern in title for pattern in ("PLANT PERFORMANCE", "PERFORMANCE", "CAPABILITY")
    )


def _looks_like_document_code(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    if re.match(r"^(SAU\d|T\d{4,}|MRT-|CCP-|GRT-|DOC_\d+)", value, re.IGNORECASE):
        return True
    has_digit = any(ch.isdigit() for ch in value)
    has_separator = any(ch in value for ch in "-_/&~")
    alpha_count = sum(ch.isalpha() for ch in value)
    return has_digit and has_separator and alpha_count >= 2 and len(value) >= 10


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.upper().strip())


def _as_text(value: Any) -> str:
    return str(value or "").strip()


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
        "candidate_status",
        "quality_issues",
        "needs_review",
        "candidate_selection_status",
        "candidate_selection_rank",
        "candidate_selection_score",
        "candidate_selection_reasons",
        "requirement_intent_equipment",
        "requirement_intent_systems",
        "requirement_intent_deliverables",
        "requirement_intent_actions",
        "requirement_intent_constraints",
        "doc_id",
        "parse_source",
        "semantic_score",
        "cross_encoder_score",
        "rrf_score",
        "rank",
        "retrieval_rank",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in candidates:
            writer.writerow({
                "Source File": c.get("source_file", "") or "itb_candidates",
                "Document No": c.get("document_no", ""),
                "Title": c["title"],
                "Equipment": c["equipment"],
                "Building": c.get("building", ""),
                "System": c.get("system", ""),
                "Deliverable": c["deliverable"],
                "Note": "",
                "match_score": f"{c['score']:.4f}",
                "itb_sources": " | ".join(c["itb_sources"][:5]),
                "candidate_status": c.get("candidate_status", ""),
                "quality_issues": c.get("quality_issues", ""),
                "needs_review": "true" if c.get("candidate_status") != "accepted" else "false",
                "candidate_selection_status": c.get("candidate_selection_status", ""),
                "candidate_selection_rank": c.get("candidate_selection_rank", ""),
                "candidate_selection_score": _fmt_optional_score(c.get("candidate_selection_score")),
                "candidate_selection_reasons": c.get("candidate_selection_reasons", ""),
                "requirement_intent_equipment": _join_list(c.get("requirement_intent_equipment")),
                "requirement_intent_systems": _join_list(c.get("requirement_intent_systems")),
                "requirement_intent_deliverables": _join_list(c.get("requirement_intent_deliverables")),
                "requirement_intent_actions": _join_list(c.get("requirement_intent_actions")),
                "requirement_intent_constraints": _join_list(c.get("requirement_intent_constraints")),
                "doc_id": c.get("doc_id", ""),
                "parse_source": c.get("parse_source", ""),
                "semantic_score": _fmt_optional_score(c.get("semantic_score")),
                "cross_encoder_score": _fmt_optional_score(c.get("cross_encoder_score")),
                "rrf_score": _fmt_optional_score(c.get("rrf_score")),
                "rank": c.get("rank", ""),
                "retrieval_rank": c.get("retrieval_rank", ""),
            })


def _fmt_optional_score(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return ""


def _join_list(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return " | ".join(str(item) for item in value if str(item).strip())


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
    from schedule_service.candidate.llm_classify_cache import LLMClassifyCache

    t_import = time.perf_counter()

    # Skip candidates whose structured fields already provide a usable scope + deliverable.
    need_llm = [c for c in candidates if _needs_llm_classification(c)]
    skipped = len(candidates) - len(need_llm)
    if skipped:
        logger.info("LLM classify: skipping {} candidates already fully extracted by regex", skipped)

    # Apply disk-cached classifications; only un-cached titles hit the LLM.
    cache = LLMClassifyCache()
    to_send: list[dict[str, Any]] = []
    cache_hits = 0
    for c in need_llm:
        hit = cache.get(c["title"])
        if hit:
            for field, value in hit.items():
                if value and (not c.get(field) or _field_needs_repair(field, c.get(field, ""))):
                    c[field] = value
            c["candidate_status"], c["quality_issues"] = _candidate_quality(c)
            cache_hits += 1
        else:
            to_send.append(c)
    if cache_hits:
        logger.info("LLM classify: {} of {} titles served from disk cache", cache_hits, len(need_llm))

    timing: dict[str, Any] = {
        "llm_enabled": True,
        "llm_import_s": 0.0,
        "llm_classify_s": 0.0,
        "llm_candidates_skipped": skipped,
        "llm_cache_hits": cache_hits,
        "llm_candidates_sent": len(to_send),
        "llm_batches": 0,
    }

    if not to_send:
        return timing

    need_llm = to_send

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
                candidate["candidate_status"], candidate["quality_issues"] = _candidate_quality(candidate)
                cache.put(candidate["title"], candidate)

    cache.save()
    timing["llm_classify_s"] = round(time.perf_counter() - t_classify, 3)
    return timing


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _read_matching_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected matching JSON list at {path}")
    return payload


def _needs_llm_classification(candidate: dict[str, Any]) -> bool:
    if not candidate.get("deliverable", "").strip():
        return True
    has_scope = any(candidate.get(field, "").strip() for field in ("equipment", "system", "building"))
    if not has_scope and not _is_global_scope_candidate(candidate):
        return True
    return _looks_like_document_code(candidate.get("equipment", ""))


def _field_needs_repair(field: str, value: str) -> bool:
    return field == "equipment" and _looks_like_document_code(value)


def _refresh_candidate_quality(candidates: list[dict[str, Any]]) -> None:
    for candidate in candidates:
        candidate["candidate_status"], candidate["quality_issues"] = _candidate_quality(candidate)
