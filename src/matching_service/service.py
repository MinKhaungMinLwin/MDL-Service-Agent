"""Application service for ITB depth to MDL matching."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from tqdm import tqdm

from matching_service.models import MatchingConfig
from matching_service.output import build_json_record, format_candidate, write_match_outputs
from matching_service.query import (
    build_cross_encoder_query,
    build_depth_filter_query,
    get_depth_context,
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
        vector_embeddings = self._embed_depth_terms(target_df)
        output_rows = []
        json_records = []

        for _, source_row in tqdm(target_df.iterrows(), total=len(target_df)):
            depth_filter_query, depth_terms = build_depth_filter_query(source_row)
            query_term_embeddings = [
                (term, vector_embeddings[term])
                for term in depth_terms
                if term in vector_embeddings
            ]
            retrieval = self.retriever.retrieve(depth_filter_query, query_term_embeddings)
            cross_encoder_query = build_cross_encoder_query(depth_terms)
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
                    self.config.retrieval_mode,
                    retrieval.candidates,
                    len(retrieval.keyword_candidates),
                    len(retrieval.semantic_candidates),
                    cross_encoder_query,
                    len(cross_encoder_candidates),
                    top_matches,
                )
            )

        write_match_outputs(output_path, output_rows, json_records, self.config.output_limit)

    def _embed_depth_terms(self, target_df: pd.DataFrame) -> dict[str, list[float]]:
        if self.embedding_service is None:
            return {}

        vector_terms = []
        for _, source_row in target_df.iterrows():
            _, depth_terms = build_depth_filter_query(source_row)
            vector_terms.extend(depth_terms)

        unique_terms = unique_preserve_order(vector_terms)
        logger.info("Embedding {} unique vector terms...", len(unique_terms))
        embeddings = self.embedding_service.embed_texts(unique_terms)
        return dict(zip(unique_terms, embeddings, strict=True))

    def _build_csv_row(
        self,
        source_row: pd.Series,
        depth_filter_query: str,
        depth_terms: list[str],
        retrieval: Any,
        cross_encoder_query: str,
        cross_encoder_candidates: list[dict[str, Any]],
        top_matches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        row = source_row.to_dict()
        row["Depth_Context"] = get_depth_context(source_row)
        row["Depth_Filter_Query"] = depth_filter_query
        row["Depth_Keywords"] = ", ".join(depth_terms)
        row["Vector_Terms"] = ", ".join(depth_terms)
        row["Retrieval_Mode"] = self.config.retrieval_mode
        row["Retrieval_Candidate_Count"] = len(retrieval.candidates)
        row["Keyword_Candidate_Count"] = len(retrieval.keyword_candidates)
        row["Semantic_Candidate_Count"] = len(retrieval.semantic_candidates)
        row["Cross_Encoder_Query"] = cross_encoder_query
        row["Cross_Encoder_Candidate_Count"] = len(cross_encoder_candidates)
        row["Search_Queries"] = depth_filter_query

        for index in range(self.config.output_limit):
            row[f"Matched_Doc_{index + 1}"] = format_candidate(top_matches[index]) if index < len(top_matches) else ""
        return row
