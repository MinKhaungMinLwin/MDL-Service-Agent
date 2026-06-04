"""Write ITB depth to MDL matching outputs."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from matching_service.models import Candidate
from matching_service.query import DEPTH_COLUMNS, get_depth_context

BASE_COLUMNS = [
    "Document",
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
    "Search Query",
    "Search Query Source",
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
        "search_query": _json_safe_value(source_row.get("Search Query", "")),
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
    """Write legacy CSV and structured JSON matching artifacts."""
    result_df = pd.DataFrame(rows)
    match_cols = [f"Matched_Doc_{index + 1}" for index in range(output_limit)]
    final_cols = [column for column in BASE_COLUMNS if column in result_df.columns] + match_cols
    result_df[final_cols].to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info("Saved successfully: {}", output_path)

    json_path = _json_output_path(output_path)
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(json_records, file, ensure_ascii=False, indent=2)
    logger.info("Structured JSON saved successfully: {}", json_path)


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
    }


def _json_safe_value(value: Any) -> Any:
    return "" if pd.isna(value) else value


def _json_output_path(csv_output_path: str | Path) -> str:
    root, _ = os.path.splitext(str(csv_output_path))
    return f"{root}.json"
