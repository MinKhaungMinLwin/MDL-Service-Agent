"""Application service for ITB depth to MDL matching."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from tqdm import tqdm

from common.text_normalizer import expand_abbreviation_terms
from matching_service.intent import build_requirement_intent
from matching_service.models import MatchingConfig
from matching_service.output import _format_json_candidate, build_json_record, format_candidate, write_match_outputs
from matching_service.query import (
    DEPTH_COLUMNS,
    build_cross_encoder_query,
    build_depth_filter_query,
    build_fulltext_query,
    build_semantic_query,
    get_depth_context,
    get_keyword_terms,
    unique_preserve_order,
)
from matching_service.repository import MDLSearchRepository
from matching_service.retrieval import DepthRetriever


class MatchingService:
    """Run depth-based MDL retrieval and cross-encoder reranking."""

    def __init__(
        self,
        repository: MDLSearchRepository,
        cross_encoder_reranker: Any | None,
        config: MatchingConfig,
        embedding_service: Any | None = None,
    ) -> None:
        self.repository = repository
        self.cross_encoder_reranker = cross_encoder_reranker
        self.config = config
        self.embedding_service = embedding_service
        self.retriever = DepthRetriever(repository, config)

    def setup(self) -> None:
        """Create indexes required by the matching workflow."""
        self.repository.setup_fulltext_index()

    def match_file(self, csv_path: str | Path, output_path: str | Path) -> None:
        """Match every ITB row in one CSV and write CSV artifacts."""
        logger.info("Reading input file: {}", csv_path)
        target_df = pd.read_csv(csv_path)
        original_count = len(target_df)
        if "Is MDL Retrieval Candidate" in target_df.columns:
            target_df = target_df[
                target_df["Is MDL Retrieval Candidate"].map(_is_mdl_retrieval_candidate)
            ]
            skipped_count = original_count - len(target_df)
            if skipped_count:
                logger.info("Skipped {} non-MDL retrieval candidate row(s)", skipped_count)
        logger.info("Rows to process: {}", len(target_df))
        if target_df.empty:
            logger.info("No target rows. Skipping.")
            return

        logger.info("Running Neo4j candidate retrieval (mode: {})...", self.config.retrieval_mode)
        semantic_embeddings = self._embed_semantic_queries(target_df)
        output_rows = []
        json_records = []

        for _, source_row in tqdm(target_df.iterrows(), total=len(target_df)):
            depth_filter_query, depth_terms = build_depth_filter_query(source_row)
            keyword_terms = get_keyword_terms(source_row)
            requirement_intent = build_requirement_intent(source_row, depth_terms, keyword_terms)
            keyword_filter_query = build_fulltext_query(expand_abbreviation_terms(keyword_terms))
            semantic_query = build_semantic_query(depth_terms, keyword_terms)
            semantic_embedding = semantic_embeddings.get(semantic_query, [])
            retrieval = self.retriever.retrieve(
                depth_filter_query,
                keyword_filter_query,
                semantic_query,
                semantic_embedding,
            )
            cross_encoder_candidates = retrieval.candidates[: self.config.retrieval_candidate_limit]
            if self.config.rerank_mode == "cross_encoder":
                if self.cross_encoder_reranker is None:
                    raise ValueError("cross_encoder_reranker is required when rerank_mode=cross_encoder")
                cross_encoder_query = build_cross_encoder_query(
                    depth_terms,
                    keyword_terms,
                    chunk_text=source_row.get("Chunk Text", ""),
                    mode=self.config.cross_encoder_query_mode,
                    intent_terms=requirement_intent.as_query_terms(),
                )
                top_matches = self.cross_encoder_reranker.rerank(
                    cross_encoder_query,
                    cross_encoder_candidates,
                    top_k=self.config.output_limit,
                )
            else:
                cross_encoder_query = ""
                top_matches = cross_encoder_candidates[: self.config.output_limit]

            output_rows.append(
                self._build_csv_row(
                    source_row,
                    depth_filter_query,
                    depth_terms,
                    keyword_terms,
                    keyword_filter_query,
                    semantic_query,
                    requirement_intent.to_dict(),
                    retrieval,
                    cross_encoder_query,
                    cross_encoder_candidates,
                    top_matches,
                )
            )
            json_records.append(
                build_json_record(
                    source_row,
                    depth_filter_query,
                    depth_terms,
                    keyword_terms,
                    keyword_filter_query,
                    semantic_query,
                    requirement_intent.to_dict(),
                    self.config.retrieval_mode,
                    retrieval.candidates,
                    len(retrieval.keyword_candidates),
                    len(retrieval.semantic_candidates),
                    self.config.rerank_mode,
                    self.config.cross_encoder_query_mode,
                    cross_encoder_query,
                    len(cross_encoder_candidates),
                    top_matches,
                )
            )

        write_match_outputs(output_path, output_rows, json_records, self.config.output_limit)

    def rerank_csv_file(self, csv_path: str | Path, output_path: str | Path) -> None:
        """Rerank existing matching candidates from a CSV artifact."""
        logger.info("Reading matching CSV file: {}", csv_path)
        records = _records_from_matching_csv(Path(csv_path), self.config.output_limit)
        if not records:
            logger.info("No structured matching records. Skipping.")
            return

        output_rows = []
        reranked_records = []
        for record in tqdm(records, total=len(records)):
            cross_encoder_candidates = [
                _normalize_retrieval_candidate(candidate)
                for candidate in record.get("retrieval_candidates", [])[: self.config.retrieval_candidate_limit]
            ]
            if self.cross_encoder_reranker is None:
                raise ValueError("cross_encoder_reranker is required to rerank existing CSV files")
            cross_encoder_query = str(record.get("cross_encoder_query", "") or "")
            top_matches = self.cross_encoder_reranker.rerank(
                cross_encoder_query,
                cross_encoder_candidates,
                top_k=self.config.output_limit,
            )
            output_rows.append(self._build_csv_row_from_record(record, cross_encoder_candidates, top_matches))
            reranked_record = dict(record)
            reranked_record["cross_encoder_query_mode"] = self.config.cross_encoder_query_mode
            reranked_record["cross_encoder_candidate_count"] = len(cross_encoder_candidates)
            reranked_record["candidates"] = [
                _format_json_candidate(candidate, rank)
                for rank, candidate in enumerate(top_matches, start=1)
            ]
            reranked_records.append(reranked_record)

        write_match_outputs(output_path, output_rows, reranked_records, self.config.output_limit)

    def _embed_semantic_queries(self, target_df: pd.DataFrame) -> dict[str, list[float]]:
        if self.embedding_service is None:
            return {}

        semantic_queries = []
        for _, source_row in target_df.iterrows():
            _, depth_terms = build_depth_filter_query(source_row)
            semantic_queries.append(build_semantic_query(depth_terms, get_keyword_terms(source_row)))

        unique_queries = unique_preserve_order(query for query in semantic_queries if query)
        logger.info("Embedding {} unique ITB semantic queries...", len(unique_queries))
        embeddings = self.embedding_service.embed_texts(unique_queries)
        return dict(zip(unique_queries, embeddings, strict=True))

    def _build_csv_row(
        self,
        source_row: pd.Series,
        depth_filter_query: str,
        depth_terms: list[str],
        keyword_terms: list[str],
        keyword_filter_query: str,
        semantic_query: str,
        requirement_intent: dict[str, Any],
        retrieval: Any,
        cross_encoder_query: str,
        cross_encoder_candidates: list[dict[str, Any]],
        top_matches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        row = source_row.to_dict()
        row["Depth_Context"] = get_depth_context(source_row)
        row["Depth_Filter_Query"] = depth_filter_query
        row["Depth_Keywords"] = ", ".join(depth_terms)
        row["Keyword_Filter_Query"] = keyword_filter_query
        row["Semantic_Query"] = semantic_query
        row["Vector_Terms"] = semantic_query
        _apply_intent_csv_fields(row, requirement_intent)
        row["Retrieval_Mode"] = self.config.retrieval_mode
        row["Retrieval_Candidate_Count"] = len(retrieval.candidates)
        row["Keyword_Candidate_Count"] = len(retrieval.keyword_candidates)
        row["Semantic_Candidate_Count"] = len(retrieval.semantic_candidates)
        row["Final_Candidate_Mode"] = self.config.rerank_mode
        row["Cross_Encoder_Query_Mode"] = (
            self.config.cross_encoder_query_mode if self.config.rerank_mode == "cross_encoder" else ""
        )
        row["Cross_Encoder_Query"] = cross_encoder_query
        row["Cross_Encoder_Candidate_Count"] = (
            len(cross_encoder_candidates) if self.config.rerank_mode == "cross_encoder" else 0
        )
        row["Search_Queries"] = depth_filter_query

        for index in range(self.config.output_limit):
            row[f"Matched_Doc_{index + 1}"] = format_candidate(top_matches[index]) if index < len(top_matches) else ""
        return row

    def _build_csv_row_from_record(
        self,
        record: dict[str, Any],
        cross_encoder_candidates: list[dict[str, Any]],
        top_matches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        row = {
            "Document": record.get("document", ""),
            "Chunk ID": record.get("chunk_id", ""),
            "Page": record.get("page", ""),
            "Keywords": record.get("keywords", ""),
            "Is MDL Retrieval Candidate": record.get("is_mdl_retrieval_candidate", ""),
            "Skip Reason": record.get("skip_reason", ""),
            "Chunk Text": record.get("chunk_text", ""),
            "Depth_Context": record.get("depth_context", ""),
            "Depth_Filter_Query": record.get("depth_filter_query", ""),
            "Depth_Filter_Terms": ", ".join(record.get("depth_filter_terms", [])),
            "Depth_Keywords": ", ".join(value for value in record.get("depths", {}).values() if value),
            "Keyword_Filter_Query": record.get("keyword_filter_query", ""),
            "Semantic_Query": record.get("semantic_query", ""),
            "Vector_Terms": record.get("vector_terms", ""),
            "Requirement_Intent_Equipment": _join_intent(record, "equipment"),
            "Requirement_Intent_Systems": _join_intent(record, "systems"),
            "Requirement_Intent_Deliverables": _join_intent(record, "deliverables"),
            "Requirement_Intent_Actions": _join_intent(record, "actions"),
            "Requirement_Intent_Constraints": _join_intent(record, "constraints"),
            "Retrieval_Mode": record.get("retrieval_mode", self.config.retrieval_mode),
            "Retrieval_Candidate_Count": record.get("retrieval_candidate_count", 0),
            "Keyword_Candidate_Count": record.get("keyword_candidate_count", 0),
            "Semantic_Candidate_Count": record.get("semantic_candidate_count", 0),
            "Final_Candidate_Mode": record.get("final_candidate_mode", self.config.rerank_mode),
            "Cross_Encoder_Query_Mode": self.config.cross_encoder_query_mode,
            "Cross_Encoder_Query": record.get("cross_encoder_query", ""),
            "Cross_Encoder_Candidate_Count": len(cross_encoder_candidates),
            "Search_Queries": record.get("depth_filter_query", ""),
        }
        for depth, value in record.get("depths", {}).items():
            row[depth] = value
        for index in range(self.config.output_limit):
            row[f"Matched_Doc_{index + 1}"] = format_candidate(top_matches[index]) if index < len(top_matches) else ""
        return row

    def rerank_json_file(self, json_path: str | Path, output_path: str | Path) -> None:
        """Rerank existing retrieval candidates from a structured matching JSON artifact."""
        logger.info("Reading structured matching file: {}", json_path)
        records = json.loads(Path(json_path).read_text(encoding="utf-8"))
        if not records:
            logger.info("No structured matching records. Skipping.")
            return

        output_rows = []
        reranked_records = []
        for record in tqdm(records, total=len(records)):
            cross_encoder_candidates = [
                _normalize_retrieval_candidate(candidate)
                for candidate in record.get("retrieval_candidates", [])[: self.config.retrieval_candidate_limit]
            ]
            if self.cross_encoder_reranker is None:
                raise ValueError("cross_encoder_reranker is required to rerank existing JSON files")
            cross_encoder_query = str(record.get("cross_encoder_query", "") or "")
            top_matches = self.cross_encoder_reranker.rerank(
                cross_encoder_query,
                cross_encoder_candidates,
                top_k=self.config.output_limit,
            )
            output_rows.append(self._build_csv_row_from_record(record, cross_encoder_candidates, top_matches))
            reranked_record = dict(record)
            reranked_record["cross_encoder_query_mode"] = self.config.cross_encoder_query_mode
            reranked_record["cross_encoder_candidate_count"] = len(cross_encoder_candidates)
            reranked_record["candidates"] = [
                _format_json_candidate(candidate, rank)
                for rank, candidate in enumerate(top_matches, start=1)
            ]
            reranked_records.append(reranked_record)

        write_match_outputs(output_path, output_rows, reranked_records, self.config.output_limit)


def _normalize_retrieval_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(candidate)
    normalized.pop("rank", None)
    return normalized


def _apply_intent_csv_fields(row: dict[str, Any], requirement_intent: dict[str, Any]) -> None:
    row["Requirement_Intent_Equipment"] = _join_values(requirement_intent.get("equipment", []))
    row["Requirement_Intent_Systems"] = _join_values(requirement_intent.get("systems", []))
    row["Requirement_Intent_Deliverables"] = _join_values(requirement_intent.get("deliverables", []))
    row["Requirement_Intent_Actions"] = _join_values(requirement_intent.get("actions", []))
    row["Requirement_Intent_Constraints"] = _join_values(requirement_intent.get("constraints", []))


def _join_intent(record: dict[str, Any], key: str) -> str:
    intent = record.get("requirement_intent", {})
    return _join_values(intent.get(key, []) if isinstance(intent, dict) else [])


def _join_values(values: Any) -> str:
    if not isinstance(values, list | tuple):
        return ""
    return " | ".join(str(value) for value in values if str(value).strip())


def _records_from_matching_csv(path: Path, output_limit: int) -> list[dict[str, Any]]:
    df = pd.read_csv(path)
    records = []
    for _, row in df.iterrows():
        candidates = []
        for index in range(1, output_limit + 1):
            prefix = f"Matched_Doc_{index}"
            doc_id = _cell_text(row.get(f"{prefix}_Doc_ID", ""))
            if not doc_id:
                continue
            candidates.append(
                {
                    "rank": index,
                    "doc_id": doc_id,
                    "source_file": _cell_text(row.get(f"{prefix}_Source_File", "")),
                    "document_no": _cell_text(row.get(f"{prefix}_Document_No", "")),
                    "title": _cell_text(row.get(f"{prefix}_Title", "")),
                    "equipment": _cell_text(row.get(f"{prefix}_Equipment", "")),
                    "building": _cell_text(row.get(f"{prefix}_Building", "")),
                    "system": _cell_text(row.get(f"{prefix}_System", "")),
                    "study_survey": _cell_text(row.get(f"{prefix}_Study_Survey", "")),
                    "others": _cell_text(row.get(f"{prefix}_Others", "")),
                    "deliverable": _cell_text(row.get(f"{prefix}_Deliverable", "")),
                    "text_content": _cell_text(row.get(f"{prefix}_Text_Content", "")),
                }
            )
        records.append(
            {
                "document": _cell_text(row.get("Document", "")),
                "chunk_id": _cell_text(row.get("Chunk ID", "")),
                "page": _cell_text(row.get("Page", "")),
                "depths": {depth: _cell_text(row.get(depth, "")) for depth in DEPTH_COLUMNS},
                "depth_context": _cell_text(row.get("Depth_Context", "")),
                "depth_filter_query": _cell_text(row.get("Depth_Filter_Query", "")),
                "keyword_filter_query": _cell_text(row.get("Keyword_Filter_Query", "")),
                "semantic_query": _cell_text(row.get("Semantic_Query", "")),
                "vector_terms": _cell_text(row.get("Vector_Terms", "")),
                "requirement_intent": {
                    "equipment": _split_values(row.get("Requirement_Intent_Equipment", "")),
                    "systems": _split_values(row.get("Requirement_Intent_Systems", "")),
                    "deliverables": _split_values(row.get("Requirement_Intent_Deliverables", "")),
                    "actions": _split_values(row.get("Requirement_Intent_Actions", "")),
                    "constraints": _split_values(row.get("Requirement_Intent_Constraints", "")),
                    "source_terms": [],
                },
                "retrieval_mode": _cell_text(row.get("Retrieval_Mode", "")),
                "retrieval_candidate_count": _cell_text(row.get("Retrieval_Candidate_Count", "")),
                "keyword_candidate_count": _cell_text(row.get("Keyword_Candidate_Count", "")),
                "semantic_candidate_count": _cell_text(row.get("Semantic_Candidate_Count", "")),
                "final_candidate_mode": _cell_text(row.get("Final_Candidate_Mode", "")),
                "cross_encoder_query_mode": _cell_text(row.get("Cross_Encoder_Query_Mode", "")),
                "cross_encoder_query": _cell_text(row.get("Cross_Encoder_Query", "")),
                "cross_encoder_candidate_count": len(candidates),
                "keywords": _cell_text(row.get("Keywords", "")),
                "is_mdl_retrieval_candidate": _cell_text(row.get("Is MDL Retrieval Candidate", "")),
                "skip_reason": _cell_text(row.get("Skip Reason", "")),
                "chunk_text": _cell_text(row.get("Chunk Text", "")),
                "retrieval_candidates": candidates,
                "candidates": candidates,
            }
        )
    return records


def _cell_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value)


def _split_values(value: Any) -> list[str]:
    text = _cell_text(value)
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def _is_mdl_retrieval_candidate(value: Any) -> bool:
    if pd.isna(value):
        return True
    return str(value).strip().casefold() not in {"false", "no", "n", "0"}
