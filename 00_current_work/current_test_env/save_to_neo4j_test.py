"""Ingest classified MDL CSV files into the test Neo4j database."""

from __future__ import annotations

import sys

from standalone_config import OUTPUT_DIR, REPO_ROOT

sys.path.append(str(REPO_ROOT / "src"))

from common.config import env_int
from common.embedding_client import AzureEmbeddingService
from common.neo4j_client import Neo4jConnection
from mdl_service.models import MDLIngestConfig
from mdl_service.repository import MDLRepository
from mdl_service.service import MDLIngestService


def main() -> None:
    """Ingest every classified MDL CSV from the current test output directory."""
    config = MDLIngestConfig(embedding_dimensions=env_int("EMBEDDING_DIMENSIONS", 1536))
    with Neo4jConnection() as conn:
        service = MDLIngestService(
            repository=MDLRepository(conn, config),
            embedding_service=AzureEmbeddingService(),
            config=config,
        )
        service.setup()
        count = service.ingest_directory(OUTPUT_DIR)
    print(f"Ingested {count} MDL documents into {config.node_label}.")


if __name__ == "__main__":
    main()
