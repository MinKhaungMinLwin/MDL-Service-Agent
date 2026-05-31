"""Neo4j repository for classified MDL documents."""

from __future__ import annotations

from typing import Any

from mdl_service.models import MDLIngestConfig

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


class MDLRepository:
    """Create MDL schema objects and upsert classified documents."""

    def __init__(self, conn: Any, config: MDLIngestConfig) -> None:
        self.conn = conn
        self.config = config

    def setup_schema(self) -> None:
        """Create the constraint and indexes required by matching."""
        with self.conn.session() as session:
            session.run(
                f"""
                CREATE CONSTRAINT {self.config.constraint_name} IF NOT EXISTS
                FOR (n:{self.config.node_label}) REQUIRE n.doc_id IS UNIQUE
                """
            )
            self._setup_fulltext_index(session)
            session.run(
                f"""
                CREATE VECTOR INDEX {self.config.vector_index_name} IF NOT EXISTS
                FOR (n:{self.config.node_label}) ON (n.embedding)
                OPTIONS {{
                  indexConfig: {{
                    `vector.dimensions`: {self.config.embedding_dimensions},
                    `vector.similarity_function`: 'cosine'
                  }}
                }}
                """
            )

    def upsert_batch(self, records: list[dict[str, Any]]) -> None:
        """Upsert one embedded document batch."""
        if not records:
            return
        with self.conn.session() as session:
            session.run(
                f"""
                UNWIND $batch AS record
                MERGE (n:{self.config.node_label} {{doc_id: record.doc_id}})
                SET n.text_content = record.text_content,
                    n.source_file = record.source_file,
                    n.document_no = record.document_no,
                    n.title = record.title,
                    n.equipment = record.equipment,
                    n.building = record.building,
                    n.system = record.system,
                    n.study_survey = record.study_survey,
                    n.others = record.others,
                    n.deliverable = record.deliverable,
                    n.embedding = record.embedding
                """,
                batch=records,
            )

    def _setup_fulltext_index(self, session: Any) -> None:
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
        session.run(
            f"""
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
            """
        )
