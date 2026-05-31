"""Run ITB depth to MDL matching from the current test environment."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger
from standalone_config import OUTPUT_DIR, REPO_ROOT

sys.path.append(str(REPO_ROOT / "src"))

from common.embedding_client import AzureEmbeddingService
from common.neo4j_client import Neo4jConnection
from matching_service.models import MatchingConfig
from matching_service.ranking import CrossEncoderReranker
from matching_service.repository import MDLSearchRepository
from matching_service.service import MatchingService

CROSS_ENCODER_MODEL = os.getenv("ITB_CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2")
CROSS_ENCODER_BATCH_SIZE = int(os.getenv("ITB_CROSS_ENCODER_BATCH_SIZE", "32"))


def main() -> None:
    """Run matching for the focused ITB section outputs."""
    config = MatchingConfig(
        retrieval_mode=os.getenv("ITB_RETRIEVAL_MODE", "keyword").strip().lower(),
        retrieval_candidate_limit=int(os.getenv("ITB_RETRIEVAL_CANDIDATES", "200")),
        output_limit=int(os.getenv("ITB_OUTPUT_LIMIT", "100")),
    )
    embedding_service = (
        AzureEmbeddingService()
        if config.retrieval_mode in {"semantic", "hybrid"}
        else None
    )
    cross_encoder_reranker = CrossEncoderReranker(
        CROSS_ENCODER_MODEL,
        batch_size=CROSS_ENCODER_BATCH_SIZE,
    )

    with Neo4jConnection() as conn:
        service = MatchingService(
            repository=MDLSearchRepository(conn, config),
            cross_encoder_reranker=cross_encoder_reranker,
            config=config,
            embedding_service=embedding_service,
        )
        service.setup()
        for csv_path, output_path in _files_to_process():
            if csv_path.exists():
                service.match_file(csv_path, output_path)
            else:
                logger.warning("Input file not found: {}", csv_path)


def _files_to_process() -> list[tuple[Path, Path]]:
    return [
        (
            OUTPUT_DIR / "output_itb_section6_focused.csv",
            OUTPUT_DIR / "output_match_all_projects_section6.csv",
        ),
        (
            OUTPUT_DIR / "output_itb_section7_focused.csv",
            OUTPUT_DIR / "output_match_all_projects_section7.csv",
        ),
    ]


if __name__ == "__main__":
    main()
