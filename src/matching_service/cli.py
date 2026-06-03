"""Command-line entrypoint for ITB depth to MDL matching."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from loguru import logger

from common.embedding_client import AzureEmbeddingService
from common.neo4j_client import Neo4jConnection
from matching_service.models import MatchingConfig
from matching_service.ranking import CrossEncoderReranker
from matching_service.repository import MDLSearchRepository
from matching_service.service import MatchingService

DEFAULT_BASE_OUTPUT_DIR = Path("output") / "current_test_env"
DEFAULT_INPUT_DIR = DEFAULT_BASE_OUTPUT_DIR / "itb_extract"
DEFAULT_OUTPUT_DIR = DEFAULT_BASE_OUTPUT_DIR / "matching"
DEFAULT_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"


def match(argv: list[str] | None = None) -> None:
    """Run matching for one or more ITB extraction CSV files."""
    parser = argparse.ArgumentParser(description="Match ITB depth extraction rows to MDL documents.")
    parser.add_argument("--input", action="append", type=Path, dest="inputs")
    parser.add_argument("--output", action="append", type=Path, dest="outputs")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--retrieval-mode",
        choices=["keyword", "semantic", "hybrid"],
        default=os.getenv("ITB_RETRIEVAL_MODE", "keyword").strip().lower(),
    )
    parser.add_argument("--retrieval-candidates", type=int, default=int(os.getenv("ITB_RETRIEVAL_CANDIDATES", "100")))
    parser.add_argument("--output-limit", type=int, default=int(os.getenv("ITB_OUTPUT_LIMIT", "20")))
    parser.add_argument(
        "--source-file",
        action="append",
        dest="source_files",
        default=None,
        help="Restrict MDL search to one source_file/project, e.g. R&N_MDL.xlsx. Repeat for multiple files.",
    )
    parser.add_argument(
        "--cross-encoder-model",
        default=os.getenv("ITB_CROSS_ENCODER_MODEL", DEFAULT_CROSS_ENCODER_MODEL),
    )
    parser.add_argument(
        "--cross-encoder-batch-size",
        type=int,
        default=int(os.getenv("ITB_CROSS_ENCODER_BATCH_SIZE", "32")),
    )
    args = parser.parse_args(argv)

    config = MatchingConfig(
        retrieval_mode=args.retrieval_mode,
        retrieval_candidate_limit=args.retrieval_candidates,
        output_limit=args.output_limit,
        source_files=tuple(args.source_files or ()),
    )
    output_dir = _scoped_output_dir(args.output_dir, config.source_files) / args.retrieval_mode
    files_to_process = _files_to_process(args.inputs, args.outputs, DEFAULT_INPUT_DIR, output_dir)
    embedding_service = AzureEmbeddingService() if config.retrieval_mode in {"semantic", "hybrid"} else None
    cross_encoder_reranker = CrossEncoderReranker(
        args.cross_encoder_model,
        batch_size=args.cross_encoder_batch_size,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    with Neo4jConnection() as conn:
        service = MatchingService(
            repository=MDLSearchRepository(conn, config),
            cross_encoder_reranker=cross_encoder_reranker,
            config=config,
            embedding_service=embedding_service,
        )
        service.setup()
        for input_path, output_path in files_to_process:
            if input_path.exists():
                output_path.parent.mkdir(parents=True, exist_ok=True)
                service.match_file(input_path, output_path)
            else:
                logger.warning("Input file not found: {}", input_path)


def _files_to_process(
    inputs: list[Path] | None,
    outputs: list[Path] | None,
    input_dir: Path,
    output_dir: Path,
) -> list[tuple[Path, Path]]:
    if inputs:
        if outputs and len(outputs) != len(inputs):
            raise ValueError("--output must be provided once per --input")
        return [
            (input_path, outputs[index] if outputs else output_dir / f"output_match_{input_path.stem}.csv")
            for index, input_path in enumerate(inputs)
        ]
    return [
        (
            input_dir / "output_itb_section6_focused.csv",
            output_dir / "output_match_all_projects_section6.csv",
        ),
        (
            input_dir / "output_itb_section7_focused.csv",
            output_dir / "output_match_all_projects_section7.csv",
        ),
    ]


def _scoped_output_dir(output_dir: Path, source_files: tuple[str, ...]) -> Path:
    if not source_files:
        return output_dir
    scope = "_".join(_safe_scope_name(Path(source_file).stem) for source_file in source_files)
    return output_dir / scope


def _safe_scope_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_") or "project"


if __name__ == "__main__":
    match()
