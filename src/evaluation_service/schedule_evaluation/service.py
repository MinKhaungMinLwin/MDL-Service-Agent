"""Evaluate generated schedule date ranges against matching ground truth.

This report is intentionally stricter than the generated schedule's internal
confidence fields. It checks whether a generated row came from a ground-truth
positive MDL document and adds simple rule/activity mismatch flags that make
obvious bad date ranges visible during iteration.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from loguru import logger

from common.json_io import read_json, write_json

ROW_ANALYSIS_HEADER = [
    "row_index",
    "doc_id",
    "source_file",
    "document_no",
    "title",
    "candidate_status",
    "quality_issues",
    "match_score",
    "source_chunks",
    "exact_gt_hit",
    "gt_positive_source_chunks",
    "date_range_status",
    "submission_type",
    "has_fa",
    "has_fc",
    "rule_query",
    "matched_rule_keyword",
    "matched_activity_name",
    "matched_activity_wbs_path",
    "risk_level",
    "risk_reasons",
    "usable_strict",
]

MISSING_GT_HEADER = [
    "section",
    "chunk_id",
    "mdl_doc_id",
    "candidate_found",
    "candidate_status",
    "generated_found",
    "date_range_status",
    "reason",
]

STOP_TOKENS = {
    "A",
    "AN",
    "AND",
    "AREA",
    "B",
    "BLOCK",
    "C",
    "D",
    "DOC",
    "DOCUMENT",
    "FOR",
    "GENERAL",
    "IN",
    "NO",
    "OF",
    "ON",
    "SYSTEM",
    "THE",
    "TO",
    "V",
    "WITH",
}

DELIVERABLE_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("p&id", ("P&ID", "P&I", "PIPING INSTRUMENT", "PIPING & INSTRUMENT")),
    ("painting", ("PAINTING", "PAINT")),
    ("foundation", ("FOUNDATION", "FDN")),
    ("technical_specification", ("TECHNICAL SPECIFICATION", "SPECIFICATION")),
    ("datasheet", ("DATASHEET", "DATA SHEET", "DATA SHEET")),
    ("system_description", ("SYSTEM DESCRIPTION", "DESCRIPTION")),
    ("design_criteria", ("DESIGN CRITERIA", "CRITERIA")),
    ("design_report", ("DESIGN REPORT", "REPORT")),
    ("design_recommendation", ("DESIGN RECOMMENDATION", "RECOMMENDATION")),
    ("arrangement", ("GENERAL ARRANGEMENT", "ARRANGEMENT", "ARRG")),
    ("outline", ("OUTLINE",)),
    ("procedure", ("PROCEDURE",)),
    ("manual", ("MANUAL", "O&M", "OPERATION AND MAINTENANCE")),
    ("calculation", ("CALCULATION", "CALC")),
    ("study", ("STUDY",)),
    ("curve", ("CURVE",)),
    ("classification", ("CLASSIFICATION",)),
    ("diagram", ("DIAGRAM",)),
    ("configuration", ("CONFIGURATION",)),
    ("list", ("LIST",)),
    ("logic", ("LOGIC",)),
)

SEVERE_FAMILIES = {"painting", "foundation"}


class ScheduleEvaluationService:
    """Build row-level and aggregate schedule quality reports."""

    def evaluate(
        self,
        ground_truth_path: Path,
        candidates_path: Path,
        generated_path: Path,
        output_dir: Path,
        sections: tuple[str, ...],
        relevance_threshold: int = 3,
    ) -> None:
        """Evaluate candidate and generated schedule artifacts."""
        ground_truth = _load_ground_truth(ground_truth_path, sections, relevance_threshold)
        candidates = _load_csv(candidates_path)
        generated_rows = _load_generated(generated_path)

        candidate_by_doc_id = {row.get("doc_id", "").strip(): row for row in candidates if row.get("doc_id")}
        generated_doc_ids = _resolve_generated_doc_ids(generated_rows, candidates)
        candidate_hits = _candidate_hits(candidates, ground_truth)
        generated_analysis = [
            _analyze_generated_row(index, row, generated_doc_ids[index - 1], candidate_by_doc_id, ground_truth)
            for index, row in enumerate(generated_rows, start=1)
        ]
        missing_ground_truth = _missing_ground_truth_rows(
            ground_truth,
            candidate_by_doc_id,
            generated_analysis,
        )
        summary = _summary(
            ground_truth,
            candidates,
            generated_rows,
            candidate_hits,
            generated_analysis,
            missing_ground_truth,
            sections,
            relevance_threshold,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(output_dir / "row_analysis.csv", ROW_ANALYSIS_HEADER, generated_analysis)
        _write_csv(output_dir / "missing_ground_truth.csv", MISSING_GT_HEADER, missing_ground_truth)
        write_json(
            output_dir / "report.json",
            {
                "ground_truth_path": str(ground_truth_path),
                "candidates_path": str(candidates_path),
                "generated_path": str(generated_path),
                "sections": list(sections),
                "summary": summary,
            },
        )
        (output_dir / "report.md").write_text(_markdown_report(summary), encoding="utf-8")
        logger.info("Saved schedule evaluation reports: {}", output_dir)


def _load_ground_truth(path: Path, sections: tuple[str, ...], threshold: int) -> dict[str, dict[str, dict[str, str]]]:
    qrels: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        required = {"section", "chunk_id", "mdl_doc_id"}
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ValueError("Ground truth CSV must contain section, chunk_id, and mdl_doc_id columns")
        for row in reader:
            section = str(row.get("section") or "").strip()
            chunk_id = str(row.get("chunk_id") or "").strip()
            doc_id = str(row.get("mdl_doc_id") or "").strip()
            if section not in sections or not chunk_id or not doc_id:
                continue
            relevance = _int_or_zero(row.get("final_relevance") or row.get("relevance"))
            label_status = str(row.get("label_status") or "").strip().lower()
            if relevance < threshold or (label_status and label_status != "positive"):
                continue
            qrels[chunk_id][doc_id] = row
    if not qrels:
        raise ValueError(f"No positive ground truth found for sections {', '.join(sections)}")
    return dict(qrels)


def _load_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def _load_generated(path: Path) -> list[dict[str, Any]]:
    rows = read_json(path)
    if not isinstance(rows, list):
        raise ValueError(f"Generated schedule JSON must contain a list: {path}")
    return rows


def _resolve_generated_doc_ids(generated_rows: list[dict[str, Any]], candidates: list[dict[str, str]]) -> list[str]:
    by_key: dict[tuple[str, str, str], str] = {}
    for candidate in candidates:
        doc_id = candidate.get("doc_id", "").strip()
        if not doc_id:
            continue
        key = _candidate_identity(candidate)
        by_key.setdefault(key, doc_id)
    return [by_key.get(_generated_identity(row), "") for row in generated_rows]


def _candidate_hits(
    candidates: list[dict[str, str]],
    ground_truth: dict[str, dict[str, dict[str, str]]],
) -> dict[str, Any]:
    candidate_doc_ids = {row.get("doc_id", "").strip() for row in candidates if row.get("doc_id")}
    accepted_doc_ids = {
        row.get("doc_id", "").strip()
        for row in candidates
        if row.get("doc_id") and row.get("candidate_status", "").strip().lower() == "accepted"
    }
    hit_pairs = []
    accepted_hit_pairs = []
    for candidate in candidates:
        doc_id = candidate.get("doc_id", "").strip()
        if not doc_id:
            continue
        source_chunks = _source_chunks(candidate.get("itb_sources", ""))
        for chunk_id in source_chunks:
            if doc_id not in ground_truth.get(chunk_id, {}):
                continue
            pair = {"chunk_id": chunk_id, "doc_id": doc_id}
            hit_pairs.append(pair)
            if candidate.get("candidate_status", "").strip().lower() == "accepted":
                accepted_hit_pairs.append(pair)
    return {
        "candidate_doc_ids": candidate_doc_ids,
        "accepted_doc_ids": accepted_doc_ids,
        "hit_pairs": hit_pairs,
        "accepted_hit_pairs": accepted_hit_pairs,
    }


def _analyze_generated_row(
    index: int,
    row: dict[str, Any],
    doc_id: str,
    candidate_by_doc_id: dict[str, dict[str, str]],
    ground_truth: dict[str, dict[str, dict[str, str]]],
) -> dict[str, Any]:
    candidate = candidate_by_doc_id.get(doc_id, {})
    source_chunks = _source_chunks(str(row.get("itb_sources") or candidate.get("itb_sources") or ""))
    gt_chunks = [chunk_id for chunk_id in source_chunks if doc_id and doc_id in ground_truth.get(chunk_id, {})]
    risk_level, reasons = _risk(row)
    has_fa = bool(str(row.get("fa_recommended") or "").strip())
    has_fc = bool(str(row.get("fc_recommended") or "").strip())
    exact_gt_hit = bool(gt_chunks)
    usable_strict = exact_gt_hit and row.get("date_range_status") == "generated" and risk_level == "low"
    return {
        "row_index": index,
        "doc_id": doc_id,
        "source_file": row.get("source_file", ""),
        "document_no": row.get("document_no", ""),
        "title": row.get("title", ""),
        "candidate_status": candidate.get("candidate_status", ""),
        "quality_issues": candidate.get("quality_issues", ""),
        "match_score": candidate.get("match_score", ""),
        "source_chunks": " | ".join(source_chunks),
        "exact_gt_hit": exact_gt_hit,
        "gt_positive_source_chunks": " | ".join(gt_chunks),
        "date_range_status": row.get("date_range_status", ""),
        "submission_type": row.get("submission_type", ""),
        "has_fa": has_fa,
        "has_fc": has_fc,
        "rule_query": row.get("rule_query", ""),
        "matched_rule_keyword": row.get("matched_rule_keyword", ""),
        "matched_activity_name": row.get("matched_activity_name", ""),
        "matched_activity_wbs_path": row.get("matched_activity_wbs_path", ""),
        "risk_level": risk_level,
        "risk_reasons": "; ".join(reasons),
        "usable_strict": usable_strict,
    }


def _missing_ground_truth_rows(
    ground_truth: dict[str, dict[str, dict[str, str]]],
    candidate_by_doc_id: dict[str, dict[str, str]],
    generated_analysis: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    generated_by_pair = {
        (chunk_id, row["doc_id"]): row
        for row in generated_analysis
        if row["doc_id"]
        for chunk_id in str(row.get("source_chunks") or "").split(" | ")
    }
    rows = []
    for chunk_id in sorted(ground_truth):
        for doc_id, gt_row in sorted(ground_truth[chunk_id].items()):
            candidate = candidate_by_doc_id.get(doc_id, {})
            candidate_found = chunk_id in _source_chunks(candidate.get("itb_sources", ""))
            generated = generated_by_pair.get((chunk_id, doc_id), {})
            rows.append(
                {
                    "section": gt_row.get("section", ""),
                    "chunk_id": chunk_id,
                    "mdl_doc_id": doc_id,
                    "candidate_found": candidate_found,
                    "candidate_status": candidate.get("candidate_status", ""),
                    "generated_found": bool(generated),
                    "date_range_status": generated.get("date_range_status", ""),
                    "reason": gt_row.get("reason", ""),
                }
            )
    return rows


def _summary(
    ground_truth: dict[str, dict[str, dict[str, str]]],
    candidates: list[dict[str, str]],
    generated_rows: list[dict[str, Any]],
    candidate_hits: dict[str, Any],
    generated_analysis: list[dict[str, Any]],
    missing_ground_truth: list[dict[str, Any]],
    sections: tuple[str, ...],
    relevance_threshold: int,
) -> dict[str, Any]:
    gt_pair_count = sum(len(doc_ids) for doc_ids in ground_truth.values())
    generated_gt_hits = [row for row in generated_analysis if row["exact_gt_hit"]]
    generated_usable = [row for row in generated_analysis if row["usable_strict"]]
    risk_counts = Counter(row["risk_level"] for row in generated_analysis)
    date_status_counts = Counter(str(row.get("date_range_status") or "") for row in generated_rows)
    candidate_status_counts = Counter(str(row.get("candidate_status") or "") for row in candidates)
    return {
        "sections": list(sections),
        "relevance_threshold": relevance_threshold,
        "ground_truth_positive_chunks": len(ground_truth),
        "ground_truth_positive_pairs": gt_pair_count,
        "candidate_rows": len(candidates),
        "candidate_status_counts": dict(candidate_status_counts),
        "candidate_exact_gt_pairs": len(candidate_hits["hit_pairs"]),
        "accepted_candidate_exact_gt_pairs": len(candidate_hits["accepted_hit_pairs"]),
        "candidate_exact_gt_pair_recall": _ratio(len(candidate_hits["hit_pairs"]), gt_pair_count),
        "accepted_candidate_exact_gt_pair_recall": _ratio(len(candidate_hits["accepted_hit_pairs"]), gt_pair_count),
        "generated_rows": len(generated_rows),
        "generated_date_status_counts": dict(date_status_counts),
        "generated_exact_gt_rows": len(generated_gt_hits),
        "generated_exact_gt_row_rate": _ratio(len(generated_gt_hits), len(generated_rows)),
        "strict_usable_rows": len(generated_usable),
        "strict_usable_row_rate": _ratio(len(generated_usable), len(generated_rows)),
        "risk_level_counts": dict(risk_counts),
        "missing_ground_truth_pairs": sum(not row["generated_found"] for row in missing_ground_truth),
    }


def _risk(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = []
    date_status = str(row.get("date_range_status") or "")
    if date_status != "generated":
        reasons.append(f"date_status={date_status or 'blank'}")
    rule_query = str(row.get("rule_query") or "")
    rule_keyword = str(row.get("matched_rule_keyword") or "")
    if not rule_keyword.strip():
        reasons.append("missing_rule_keyword")
    query_family = _deliverable_family(rule_query)
    rule_family = _deliverable_family(rule_keyword)
    if query_family and rule_family and query_family != rule_family:
        reasons.append(f"deliverable_family_mismatch:{query_family}->{rule_family}")
    if rule_family in SEVERE_FAMILIES and query_family != rule_family:
        reasons.append(f"severe_rule_family:{rule_family}")
    if _token_overlap_count(rule_query, rule_keyword) == 0:
        reasons.append("rule_token_no_overlap")
    scope_text = " ".join(
        str(row.get(key) or "") for key in ("equipment", "system", "building") if str(row.get(key) or "").strip()
    )
    activity_text = " ".join(
        str(row.get(key) or "") for key in ("matched_activity_name", "matched_activity_wbs_path")
    )
    if scope_text and _token_overlap_count(scope_text, activity_text) == 0:
        reasons.append("activity_scope_no_overlap")

    severe_reason = any(
        reason.startswith(("date_status=", "severe_rule_family:")) or "painting" in reason or "foundation" in reason
        for reason in reasons
    )
    if severe_reason:
        return "high", reasons
    if reasons:
        return "medium", reasons
    return "low", reasons


def _candidate_identity(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        _norm(row.get("Source File", "")),
        _norm(row.get("Document No", "")),
        _norm(row.get("Title", "")),
    )


def _generated_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _norm(str(row.get("source_file") or "")),
        _norm(str(row.get("document_no") or "")),
        _norm(str(row.get("title") or "")),
    )


def _source_chunks(value: str) -> list[str]:
    chunks = []
    seen = set()
    for chunk_id in re.findall(r"([A-Za-z0-9_.&-]+_chunk_\d+)", value):
        if chunk_id not in seen:
            seen.add(chunk_id)
            chunks.append(chunk_id)
    return chunks


def _deliverable_family(value: str) -> str:
    text = value.upper().replace("P&I DIAGRAM", "P&ID").replace("P&I", "P&ID")
    for family, patterns in DELIVERABLE_FAMILIES:
        if any(pattern in text for pattern in patterns):
            return family
    return ""


def _token_overlap_count(left: str, right: str) -> int:
    return len(_tokens(left).intersection(_tokens(right)))


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Z0-9]+", value.upper())
        if len(token) > 1 and token not in STOP_TOKENS
    }


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _write_csv(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Schedule Evaluation Report",
        "",
        "## Summary",
        "",
        f"- Sections: {', '.join(summary['sections'])}",
        f"- Ground-truth positive chunks: {summary['ground_truth_positive_chunks']}",
        f"- Ground-truth positive pairs: {summary['ground_truth_positive_pairs']}",
        f"- Candidate rows: {summary['candidate_rows']}",
        f"- Candidate status counts: {summary['candidate_status_counts']}",
        f"- Candidate exact GT pairs: {summary['candidate_exact_gt_pairs']}",
        f"- Accepted candidate exact GT pairs: {summary['accepted_candidate_exact_gt_pairs']}",
        f"- Generated rows: {summary['generated_rows']}",
        f"- Generated date status counts: {summary['generated_date_status_counts']}",
        f"- Generated exact GT rows: {summary['generated_exact_gt_rows']}",
        f"- Strict usable rows: {summary['strict_usable_rows']}",
        f"- Risk level counts: {summary['risk_level_counts']}",
        "",
        "## Interpretation",
        "",
        "Strict usable rows are generated rows that exactly match a positive ground-truth MDL document, "
        "have `date_range_status=generated`, and have no rule/activity risk flags.",
        "",
    ]
    return "\n".join(lines)
