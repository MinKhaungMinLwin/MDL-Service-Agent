"""Ingest classified MDL CSV files into the test Neo4j database."""

from __future__ import annotations

import sys

from mdl_runtime.config import EMBEDDING_DIMENSIONS, OUTPUT_DIR, REPO_ROOT
from mdl_runtime.embeddings import UnifiedEmbeddingService
from mdl_runtime.neo4j_connection import Neo4jConnection

sys.path.append(str(REPO_ROOT / "src"))

from mdl_service.models import MDLIngestConfig
from mdl_service.repository import MDLRepository
from mdl_service.service import MDLIngestService


def main() -> None:
    """Ingest every classified MDL CSV from the current test output directory."""
    config = MDLIngestConfig(embedding_dimensions=EMBEDDING_DIMENSIONS)
    with Neo4jConnection() as conn:
        service = MDLIngestService(
            repository=MDLRepository(conn, config),
            embedding_service=UnifiedEmbeddingService.build_default(),
            config=config,
        )
        service.setup()
        count = service.ingest_directory(OUTPUT_DIR)
    print(f"Ingested {count} MDL documents into {config.node_label}.")


if __name__ == "__main__":
    main()
