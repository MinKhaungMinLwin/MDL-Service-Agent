"""Application service for ITB depth to MDL matching."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from tqdm import tqdm

from common.text_normalizer import expand_abbreviation_terms
from matching_service.models import MatchingConfig
from matching_service.output import _format_json_candidate, build_json_record, format_candidate, write_match_outputs
from matching_service.query import (
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
        cross_encoder_reranker: Any,
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
        """Match every ITB row in one CSV and write CSV/JSON artifacts."""
        logger.info("Reading input file: {}", csv_path)
        target_df = pd.read_csv(csv_path)
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
            keyword_filter_query = build_fulltext_query(expand_abbreviation_terms(keyword_terms))
            semantic_query = build_semantic_query(depth_terms, keyword_terms)
            semantic_embedding = semantic_embeddings.get(semantic_query, [])
            retrieval = self.retriever.retrieve(
                depth_filter_query,
                keyword_filter_query,
                semantic_query,
                semantic_embedding,
            )
            cross_encoder_query = build_cross_encoder_query(
                depth_terms,
                keyword_terms,
                chunk_text=source_row.get("Chunk Text", ""),
                mode=self.config.cross_encoder_query_mode,
            )
            cross_encoder_candidates = retrieval.candidates[: self.config.retrieval_candidate_limit]
            top_matches = self.cross_encoder_reranker.rerank(
                cross_encoder_query,
                cross_encoder_candidates,
                top_k=self.config.output_limit,
            )

            output_rows.append(
                self._build_csv_row(
                    source_row,
                    depth_filter_query,
                    depth_terms,
                    keyword_terms,
                    keyword_filter_query,
                    semantic_query,
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
                    self.config.retrieval_mode,
                    retrieval.candidates,
                    len(retrieval.keyword_candidates),
                    len(retrieval.semantic_candidates),
                    self.config.cross_encoder_query_mode,
                    cross_encoder_query,
                    len(cross_encoder_candidates),
                    top_matches,
                )
            )

        write_match_outputs(output_path, output_rows, json_records, self.config.output_limit)

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
        row["Retrieval_Mode"] = self.config.retrieval_mode
        row["Retrieval_Candidate_Count"] = len(retrieval.candidates)
        row["Keyword_Candidate_Count"] = len(retrieval.keyword_candidates)
        row["Semantic_Candidate_Count"] = len(retrieval.semantic_candidates)
        row["Cross_Encoder_Query_Mode"] = self.config.cross_encoder_query_mode
        row["Cross_Encoder_Query"] = cross_encoder_query
        row["Cross_Encoder_Candidate_Count"] = len(cross_encoder_candidates)
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
            "Chunk Text": record.get("chunk_text", ""),
            "Depth_Context": record.get("depth_context", ""),
            "Depth_Filter_Query": record.get("depth_filter_query", ""),
            "Depth_Filter_Terms": ", ".join(record.get("depth_filter_terms", [])),
            "Depth_Keywords": ", ".join(value for value in record.get("depths", {}).values() if value),
            "Keyword_Filter_Query": record.get("keyword_filter_query", ""),
            "Semantic_Query": record.get("semantic_query", ""),
            "Vector_Terms": record.get("vector_terms", ""),
            "Retrieval_Mode": record.get("retrieval_mode", self.config.retrieval_mode),
            "Retrieval_Candidate_Count": record.get("retrieval_candidate_count", 0),
            "Keyword_Candidate_Count": record.get("keyword_candidate_count", 0),
            "Semantic_Candidate_Count": record.get("semantic_candidate_count", 0),
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


def _normalize_retrieval_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(candidate)
    normalized.pop("rank", None)
    return normalized
