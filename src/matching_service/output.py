"""Write ITB depth to MDL matching outputs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from matching_service.models import Candidate
from matching_service.query import DEPTH_COLUMNS, get_depth_context

BASE_COLUMNS = [
    "Document",
    "Chunk ID",
    "Page",
    "1st Depth",
    "2nd Depth",
    "3rd Depth",
    "4th Depth",
    "5th Depth",
    "Depth_Context",
    "Depth_Filter_Query",
    "Depth_Keywords",
    "Keyword_Filter_Query",
    "Semantic_Query",
    "Vector_Terms",
    "Retrieval_Mode",
    "Retrieval_Candidate_Count",
    "Keyword_Candidate_Count",
    "Semantic_Candidate_Count",
    "Cross_Encoder_Query_Mode",
    "Cross_Encoder_Query",
    "Cross_Encoder_Candidate_Count",
    "Keywords",
    "Is MDL Retrieval Candidate",
    "Skip Reason",
    "Search_Queries",
    "Chunk Text",
]


def format_candidate(candidate: Candidate) -> str:
    """Format one matched MDL document for the legacy CSV columns."""
    project = (
        str(candidate["source_file"])
        .replace("_MDL.xlsx", "")
        .replace("_classified.csv", "")
        .replace(".xlsx", "")
    )
    parts = []
    if candidate.get("cross_encoder_score") is not None:
        parts.append(f"CrossEncoder: {candidate['cross_encoder_score']:.4f}")
    if candidate.get("bm25_score") is not None:
        parts.append(f"BM25: {candidate['bm25_score']:.4f}")
    if candidate.get("keyword_rrf_score") is not None:
        parts.append(f"KeywordRRF: {candidate['keyword_rrf_score']:.4f}")
    if candidate.get("keyword_score") is not None:
        parts.append(f"Keyword: {candidate['keyword_score']:.4f}")
    if candidate.get("semantic_score") is not None:
        parts.append(f"Semantic: {candidate['semantic_score']:.4f}")
    if candidate.get("rrf_score") is not None:
        parts.append(f"RRF: {candidate['rrf_score']:.4f}")
    document_no = str(candidate.get("document_no") or "").strip()
    title = f"{document_no} - {candidate['title']}" if document_no else candidate["title"]
    return f"[{project}] {title} ({' / '.join(parts) if parts else 'No score'})"


def build_json_record(
    source_row: Mapping[str, Any],
    depth_filter_query: str,
    depth_filter_terms: list[str],
    keyword_terms: list[str],
    keyword_filter_query: str,
    semantic_query: str,
    retrieval_mode: str,
    retrieval_candidates: list[Candidate],
    keyword_candidate_count: int,
    semantic_candidate_count: int,
    cross_encoder_query_mode: str,
    cross_encoder_query: str,
    cross_encoder_candidate_count: int,
    top_matches: list[Candidate],
) -> dict[str, Any]:
    """Build one structured matching output record."""
    return {
        "document": _json_safe_value(source_row.get("Document", "")),
        "chunk_id": _json_safe_value(source_row.get("Chunk ID", "")),
        "page": _json_safe_value(source_row.get("Page", "")),
        "depths": {
            depth: _json_safe_value(source_row.get(depth, ""))
            for depth in DEPTH_COLUMNS
        },
        "depth_context": get_depth_context(source_row),
        "depth_filter_query": depth_filter_query,
        "depth_filter_terms": depth_filter_terms,
        "keyword_filter_query": keyword_filter_query,
        "semantic_query": semantic_query,
        "vector_terms": semantic_query,
        "retrieval_mode": retrieval_mode,
        "retrieval_candidate_count": len(retrieval_candidates),
        "keyword_candidate_count": keyword_candidate_count,
        "semantic_candidate_count": semantic_candidate_count,
        "cross_encoder_query_mode": cross_encoder_query_mode,
        "cross_encoder_query": cross_encoder_query,
        "cross_encoder_candidate_count": cross_encoder_candidate_count,
        "keywords": _json_safe_value(source_row.get("Keywords", "")),
        "is_mdl_retrieval_candidate": _json_safe_value(source_row.get("Is MDL Retrieval Candidate", "")),
        "skip_reason": _json_safe_value(source_row.get("Skip Reason", "")),
        "chunk_text": _json_safe_value(source_row.get("Chunk Text", "")),
        "retrieval_candidates": [
            _format_retrieval_candidate(candidate, rank)
            for rank, candidate in enumerate(retrieval_candidates, start=1)
        ],
        "candidates": [
            _format_json_candidate(candidate, rank)
            for rank, candidate in enumerate(top_matches, start=1)
        ],
    }


def write_match_outputs(
    output_path: str | Path,
    rows: list[dict[str, Any]],
    json_records: list[dict[str, Any]],
    output_limit: int,
) -> None:
    """Write matching artifacts as CSV."""
    rows = [_with_candidate_columns(row, record, output_limit) for row, record in zip(rows, json_records, strict=True)]
    result_df = pd.DataFrame(rows)
    match_cols = [f"Matched_Doc_{index + 1}" for index in range(output_limit)]
    base_cols = [column for column in BASE_COLUMNS if column in result_df.columns]
    detail_cols = [column for column in result_df.columns if column not in set(base_cols + match_cols)]
    final_cols = base_cols + match_cols + detail_cols
    result_df[final_cols].to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info("Saved successfully: {}", output_path)


def _format_json_candidate(candidate: Candidate, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "final_rank": candidate.get("final_rank"),
        "retrieval_rank": candidate.get("retrieval_rank"),
        "bm25_rank": candidate.get("bm25_rank"),
        "semantic_rank": candidate.get("semantic_rank"),
        "doc_id": _json_safe_value(candidate.get("doc_id")),
        "source_file": _json_safe_value(candidate.get("source_file")),
        "document_no": _json_safe_value(candidate.get("document_no")),
        "title": _json_safe_value(candidate.get("title")),
        "equipment": _json_safe_value(candidate.get("equipment")),
        "building": _json_safe_value(candidate.get("building")),
        "system": _json_safe_value(candidate.get("system")),
        "study_survey": _json_safe_value(candidate.get("study_survey")),
        "others": _json_safe_value(candidate.get("others")),
        "deliverable": _json_safe_value(candidate.get("deliverable")),
        "text_content": _json_safe_value(candidate.get("text_content")),
        "bm25_score": candidate.get("bm25_score"),
        "keyword_rrf_score": candidate.get("keyword_rrf_score"),
        "keyword_score": candidate.get("keyword_score"),
        "semantic_score": candidate.get("semantic_score"),
        "rrf_score": candidate.get("rrf_score"),
        "cross_encoder_score": candidate.get("cross_encoder_score"),
        "matched_terms": candidate.get("matched_terms", []),
    }


def _format_retrieval_candidate(candidate: Candidate, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "retrieval_rank": candidate.get("retrieval_rank"),
        "doc_id": _json_safe_value(candidate.get("doc_id")),
        "source_file": _json_safe_value(candidate.get("source_file")),
        "document_no": _json_safe_value(candidate.get("document_no")),
        "title": _json_safe_value(candidate.get("title")),
        "equipment": _json_safe_value(candidate.get("equipment")),
        "building": _json_safe_value(candidate.get("building")),
        "system": _json_safe_value(candidate.get("system")),
        "study_survey": _json_safe_value(candidate.get("study_survey")),
        "others": _json_safe_value(candidate.get("others")),
        "deliverable": _json_safe_value(candidate.get("deliverable")),
        "text_content": _json_safe_value(candidate.get("text_content")),
        "bm25_rank": candidate.get("bm25_rank"),
        "semantic_rank": candidate.get("semantic_rank"),
        "bm25_score": candidate.get("bm25_score"),
        "keyword_rrf_score": candidate.get("keyword_rrf_score"),
        "keyword_score": candidate.get("keyword_score"),
        "semantic_score": candidate.get("semantic_score"),
        "rrf_score": candidate.get("rrf_score"),
        "matched_terms": candidate.get("matched_terms", []),
    }


def _json_safe_value(value: Any) -> Any:
    return "" if pd.isna(value) else value


def _with_candidate_columns(row: dict[str, Any], record: dict[str, Any], output_limit: int) -> dict[str, Any]:
    resolved = dict(row)
    candidates = record.get("candidates", [])
    retrieval_candidates = record.get("retrieval_candidates", [])
    resolved["Matched_Doc_IDs"] = _joined_candidate_values(candidates, "doc_id")
    resolved["Retrieval_Doc_IDs"] = _joined_candidate_values(retrieval_candidates, "doc_id")
    for index in range(output_limit):
        candidate = candidates[index] if index < len(candidates) else {}
        prefix = f"Matched_Doc_{index + 1}"
        resolved[f"{prefix}_Doc_ID"] = _json_safe_value(candidate.get("doc_id", ""))
        resolved[f"{prefix}_Source_File"] = _json_safe_value(candidate.get("source_file", ""))
        resolved[f"{prefix}_Document_No"] = _json_safe_value(candidate.get("document_no", ""))
        resolved[f"{prefix}_Title"] = _json_safe_value(candidate.get("title", ""))
        resolved[f"{prefix}_Equipment"] = _json_safe_value(candidate.get("equipment", ""))
        resolved[f"{prefix}_Building"] = _json_safe_value(candidate.get("building", ""))
        resolved[f"{prefix}_System"] = _json_safe_value(candidate.get("system", ""))
        resolved[f"{prefix}_Study_Survey"] = _json_safe_value(candidate.get("study_survey", ""))
        resolved[f"{prefix}_Others"] = _json_safe_value(candidate.get("others", ""))
        resolved[f"{prefix}_Deliverable"] = _json_safe_value(candidate.get("deliverable", ""))
        resolved[f"{prefix}_Text_Content"] = _json_safe_value(candidate.get("text_content", ""))
    return resolved


def _joined_candidate_values(candidates: Any, field: str) -> str:
    values = []
    seen = set()
    for candidate in candidates if isinstance(candidates, list) else []:
        value = str(candidate.get(field) or "").strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return "|".join(values)
