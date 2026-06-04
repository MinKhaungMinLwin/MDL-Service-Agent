"""Neo4j repository for MDL keyword and semantic retrieval."""

from __future__ import annotations

from typing import Any

from matching_service.models import Candidate, MatchingConfig

FULLTEXT_PROPERTIES = [
    "title",
    "equipment",
    "building",
    "system",
    "study_survey",
    "others",
    "deliverable",
    "text_content",
]


class MDLSearchRepository:
    """Query MDL documents stored in Neo4j full-text and vector indexes."""

    def __init__(self, conn: Any, config: MatchingConfig) -> None:
        self.conn = conn
        self.config = config

    def setup_fulltext_index(self) -> None:
        """Create the MDL full-text index if needed."""
        with self.conn.session() as session:
            result = session.run(
                """
                SHOW INDEXES YIELD name, type, properties
                WHERE name = $index_name AND type = "FULLTEXT"
                RETURN properties
                """,
                index_name=self.config.fulltext_index_name,
            ).single()
            if result and set(result["properties"]) != set(FULLTEXT_PROPERTIES):
                session.run(f"DROP INDEX {self.config.fulltext_index_name} IF EXISTS")
            session.run(f"""
            CREATE FULLTEXT INDEX {self.config.fulltext_index_name} IF NOT EXISTS
            FOR (n:{self.config.node_label})
            ON EACH [
                n.title,
                n.equipment,
                n.building,
                n.system,
                n.study_survey,
                n.others,
                n.deliverable,
                n.text_content
            ]
            """)

    def search_keyword(self, fulltext_query: str) -> list[Candidate]:
        """Search MDL documents through the Neo4j full-text index."""
        if not fulltext_query:
            return []

        query = """
        CALL db.index.fulltext.queryNodes($index_name, $search_query, {limit: $search_limit})
        YIELD node, score
        WHERE size($source_files) = 0 OR node.source_file IN $source_files
        RETURN node.doc_id AS doc_id,
               node.source_file AS source_file,
               node.document_no AS document_no,
               node.title AS title,
               node.system AS system,
               node.equipment AS equipment,
               node.building AS building,
               node.study_survey AS study_survey,
               node.others AS others,
               node.deliverable AS deliverable,
               node.text_content AS text_content,
               node.embedding AS embedding,
               score AS bm25_score
        ORDER BY score DESC
        LIMIT $limit
        """
        candidates = self._run(
            query,
            index_name=self.config.fulltext_index_name,
            search_query=fulltext_query,
            search_limit=self._search_limit(),
            limit=self.config.retrieval_candidate_limit,
            source_files=list(self.config.source_files),
        )
        for rank, candidate in enumerate(candidates, start=1):
            candidate["bm25_rank"] = rank
            candidate["retrieval_rank"] = rank
        return candidates

    def search_semantic(self, query_embedding: list[float], semantic_query: str) -> list[Candidate]:
        """Search MDL documents through the Neo4j vector index."""
        if not query_embedding:
            return []

        query = f"""
        CALL db.index.vector.queryNodes("{self.config.vector_index_name}", $search_limit, $embedding)
        YIELD node, score
        WHERE size($source_files) = 0 OR node.source_file IN $source_files
        RETURN node.doc_id AS doc_id,
               node.source_file AS source_file,
               node.document_no AS document_no,
               node.title AS title,
               node.system AS system,
               node.equipment AS equipment,
               node.building AS building,
               node.study_survey AS study_survey,
               node.others AS others,
               node.deliverable AS deliverable,
               node.text_content AS text_content,
               score AS semantic_score
        ORDER BY score DESC
        LIMIT $limit
        """
        candidates = self._run(
            query,
            embedding=query_embedding,
            search_limit=self._search_limit(),
            limit=self.config.retrieval_candidate_limit,
            source_files=list(self.config.source_files),
        )
        for rank, candidate in enumerate(candidates, start=1):
            candidate["semantic_rank"] = rank
            candidate["retrieval_rank"] = rank
            candidate["matched_terms"] = [semantic_query]
        return candidates

    def _run(self, query: str, **parameters: Any) -> list[Candidate]:
        with self.conn.session() as session:
            return [dict(record) for record in session.run(query, **parameters)]

    def _search_limit(self) -> int:
        if not self.config.source_files:
            return self.config.retrieval_candidate_limit
        return self.config.retrieval_candidate_limit * 20
