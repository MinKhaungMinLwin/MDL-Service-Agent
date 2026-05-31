"""Command-line entrypoints for MDL classification and ingestion."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from common.config import env_int, required_env
from common.embedding_client import AzureEmbeddingService
from common.neo4j_client import Neo4jConnection
from common.openai_client import build_azure_openai_client
from mdl_service.classification import DEFAULT_CLASSIFICATION_PROMPT_PATH, MDLClassifier, load_system_prompt
from mdl_service.loader import list_excel_files
from mdl_service.models import MDLIngestConfig
from mdl_service.repository import MDLRepository
from mdl_service.service import MDLClassificationService, MDLIngestService

DEFAULT_DATA_DIR = Path("04_data") / "current_test_env" / "data"
DEFAULT_OUTPUT_DIR = Path("output") / "current_test_env"


def classify(argv: list[str] | None = None) -> None:
    """Classify MDL Excel files and write *_classified.csv outputs."""
    parser = argparse.ArgumentParser(description="Classify MDL workbook titles with Azure OpenAI.")
    parser.add_argument("requested_file", nargs="?", help="Optional workbook filename inside --data-dir.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=Path(os.getenv("PROMPT_FILE", DEFAULT_CLASSIFICATION_PROMPT_PATH)),
    )
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--batch-delay-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)

    client = build_azure_openai_client(
        api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
        default_api_version="2024-12-01-preview",
        timeout=1200.0,
    )
    service = MDLClassificationService(
        classifier=MDLClassifier(
            client=client,
            model=required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
            system_prompt=load_system_prompt(args.prompt_file),
        ),
        batch_size=args.batch_size,
        batch_delay_seconds=args.batch_delay_seconds,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for input_path in list_excel_files(args.data_dir, args.requested_file):
        if not input_path.exists():
            print(f"[ERROR] File not found: {input_path}")
            continue
        output_path = args.output_dir / f"{input_path.stem}_classified.csv"
        count = service.classify_file(input_path, output_path)
        print(f"[SAVED] {output_path} ({count} rows)")


def ingest(argv: list[str] | None = None) -> None:
    """Ingest classified MDL CSV files into Neo4j."""
    parser = argparse.ArgumentParser(description="Embed and ingest classified MDL CSV files into Neo4j.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--embedding-dimensions", type=int, default=env_int("EMBEDDING_DIMENSIONS", 1536))
    args = parser.parse_args(argv)

    config = MDLIngestConfig(embedding_dimensions=args.embedding_dimensions)
    with Neo4jConnection() as conn:
        service = MDLIngestService(
            repository=MDLRepository(conn, config),
            embedding_service=AzureEmbeddingService(),
            config=config,
        )
        service.setup()
        count = service.ingest_directory(args.input_dir)
    print(f"Ingested {count} MDL documents into {config.node_label}.")


if __name__ == "__main__":
    classify()
