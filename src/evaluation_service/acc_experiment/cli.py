"""CLI entrypoints for ACC experiment selection and evaluation."""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from pathlib import Path
from typing import Any

from common.config import required_env
from common.embedding_client import AzureEmbeddingService
from common.neo4j_client import Neo4jConnection
from common.openai_client import build_azure_openai_client
from common.prompts import load_prompt
from evaluation_service.acc_experiment.document_level import build_document_level_outputs
from evaluation_service.acc_experiment.evaluation import evaluate_acc_experiment
from evaluation_service.acc_experiment.final_selector import (
    DEFAULT_FINAL_SELECTOR_PROMPT_PATH,
    ACCFinalSelectorConfig,
    ACCFinalSelectorService,
)
from matching_service.models import MatchingConfig
from matching_service.ranking import create_reranker
from matching_service.repository import MDLSearchRepository
from matching_service.service import MatchingService

DEFAULT_BASE_DIR = Path("output") / "current_test_env" / "acc_experiment"
DEFAULT_MATCHING_DIR = DEFAULT_BASE_DIR / "matching"
DEFAULT_ITB_FILTER_DIR = DEFAULT_BASE_DIR / "itb_filter"
DEFAULT_SAME_PROJECT_MATCHING_DIR = DEFAULT_BASE_DIR / "matching_same_project"
DEFAULT_FULL_NEO4J_MATCHING_DIR = DEFAULT_BASE_DIR / "matching_full_neo4j"
DEFAULT_SELECTION_DIR = DEFAULT_BASE_DIR / "llm_final_selection"
DEFAULT_EVALUATION_DIR = DEFAULT_BASE_DIR / "evaluation"
DEFAULT_GROUND_TRUTH_PATH = DEFAULT_BASE_DIR / "ground_truth" / "acc_itb_mdl_ground_truth.csv"
DEFAULT_SELECTION_PATH = DEFAULT_SELECTION_DIR / "acc_llm_final_selection.csv"
DEFAULT_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
DEFAULT_SCOPE_SOURCE_FILES = {
    "Fadhili_ITB": "Fadhili_MDL.xlsx",
    "R_N_ITB": "R&N_MDL.xlsx",
    "Turkistan_ITB": "Turkistan_MDL.xlsx",
}


def match(argv: list[str] | None = None) -> None:
    """Run ACC hybrid matching for same-project and/or full-Neo4j modes."""
    parser = argparse.ArgumentParser(description="Run ACC hybrid matching with cross-encoder reranking.")
    parser.add_argument("--itb-filter-dir", type=Path, default=DEFAULT_ITB_FILTER_DIR)
    parser.add_argument("--same-project-output-dir", type=Path, default=DEFAULT_SAME_PROJECT_MATCHING_DIR)
    parser.add_argument("--full-neo4j-output-dir", type=Path, default=DEFAULT_FULL_NEO4J_MATCHING_DIR)
    parser.add_argument("--scope", action="append", dest="scopes")
    parser.add_argument(
        "--mode",
        choices=["same_project", "full_neo4j", "both"],
        default="both",
        help="Which ACC matching mode to run.",
    )
    parser.add_argument("--retrieval-candidates", type=int, default=200)
    parser.add_argument("--output-limit", type=int, default=50)
    parser.add_argument("--cross-encoder-query-mode", choices=["structured", "full_chunk"], default="full_chunk")
    parser.add_argument(
        "--cross-encoder-model",
        default=os.getenv("ITB_CROSS_ENCODER_MODEL", DEFAULT_CROSS_ENCODER_MODEL),
    )
    parser.add_argument(
        "--cross-encoder-batch-size",
        type=int,
        default=int(os.getenv("ITB_CROSS_ENCODER_BATCH_SIZE", "32")),
    )
    parser.add_argument(
        "--reranker-backend",
        choices=["auto", "sentence_transformers", "transformers"],
        default=os.getenv("ITB_RERANKER_BACKEND", "auto").strip().lower(),
    )
    args = parser.parse_args(argv)

    scopes = args.scopes or list(DEFAULT_SCOPE_SOURCE_FILES)
    reranker = create_reranker(
        args.cross_encoder_model,
        batch_size=args.cross_encoder_batch_size,
        backend=args.reranker_backend,
    )
    embedding_service = AzureEmbeddingService()
    modes = ["same_project", "full_neo4j"] if args.mode == "both" else [args.mode]

    with Neo4jConnection() as conn:
        for mode in modes:
            for scope in scopes:
                if scope not in DEFAULT_SCOPE_SOURCE_FILES:
                    raise ValueError(f"Unknown ACC scope: {scope}")
                input_path = args.itb_filter_dir / scope / "itb_acc_chunks.csv"
                if not input_path.exists():
                    print(f"Skipping missing ACC ITB chunks: {input_path}")
                    continue
                source_files = (DEFAULT_SCOPE_SOURCE_FILES[scope],) if mode == "same_project" else ()
                output_root = args.same_project_output_dir if mode == "same_project" else args.full_neo4j_output_dir
                output_path = output_root / scope / "hybrid" / "output_match_itb_acc_chunks.csv"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                config = MatchingConfig(
                    retrieval_mode="hybrid",
                    retrieval_candidate_limit=args.retrieval_candidates,
                    output_limit=args.output_limit,
                    cross_encoder_query_mode=args.cross_encoder_query_mode,
                    source_files=source_files,
                )
                service = MatchingService(
                    repository=MDLSearchRepository(conn, config),
                    cross_encoder_reranker=reranker,
                    config=config,
                    embedding_service=embedding_service,
                )
                service.setup()
                filtered_input_path = _write_acc_positive_temp_csv(input_path)
                try:
                    service.match_file(filtered_input_path, output_path)
                finally:
                    filtered_input_path.unlink(missing_ok=True)
                print(f"Saved {mode} ACC matching for {scope}: {output_path}")


def select_final(argv: list[str] | None = None) -> None:
    """Run LLM final selection on ACC hybrid matching outputs."""
    parser = argparse.ArgumentParser(description="Run ACC LLM final selector from cross-encoder Top-K candidates.")
    parser.add_argument("--matching-dir", type=Path, default=DEFAULT_MATCHING_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_SELECTION_DIR)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_FINAL_SELECTOR_PROMPT_PATH)
    parser.add_argument("--model", default=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"))
    parser.add_argument("--top-k", type=int, default=int(os.getenv("ACC_FINAL_SELECTOR_TOP_K", "20")))
    parser.add_argument(
        "--candidate-batch-size",
        type=int,
        default=int(os.getenv("ACC_FINAL_SELECTOR_CANDIDATE_BATCH_SIZE", "20")),
        help="Number of cross-encoder candidates to send in each LLM selector call.",
    )
    parser.add_argument("--llm-retries", type=int, default=int(os.getenv("ACC_FINAL_SELECTOR_LLM_RETRIES", "2")))
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=int(os.getenv("ACC_FINAL_SELECTOR_MAX_CONCURRENCY", "1")),
        help="Number of LLM selector candidate batches to run concurrently.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=int(os.getenv("ACC_FINAL_SELECTOR_MAX_RECORDS", "0")),
        help="Limit records for token/cost test runs. Use 0 to process all records.",
    )
    args = parser.parse_args(argv)

    service = ACCFinalSelectorService(
        config=ACCFinalSelectorConfig(
            model=args.model or required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
            top_k=args.top_k,
            candidate_batch_size=args.candidate_batch_size,
            llm_retries=args.llm_retries,
            max_concurrency=args.max_concurrency,
            max_records=args.max_records,
        ),
        client=build_azure_openai_client(
            api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
            default_api_version="2024-12-01-preview",
            timeout=1200.0,
        ),
        prompt=load_prompt(args.prompt_file),
    )
    count = service.select(args.matching_dir, args.output_dir)
    print(f"Saved {count} ACC final selected rows: {args.output_dir / 'acc_llm_final_selection.csv'}")


def evaluate_matching(argv: list[str] | None = None) -> None:
    """Evaluate ACC retrieval, cross-encoder, and optional LLM final selection."""
    parser = argparse.ArgumentParser(description="Evaluate ACC experiment matching outputs.")
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    parser.add_argument("--matching-dir", type=Path, default=DEFAULT_MATCHING_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EVALUATION_DIR)
    parser.add_argument("--llm-selection", type=Path, default=DEFAULT_SELECTION_PATH)
    parser.add_argument("--no-llm-selection", action="store_true")
    parser.add_argument("--retrieval-k", type=int, default=100)
    parser.add_argument("--cross-encoder-k", type=int, default=20)
    parser.add_argument("--llm-k", type=int, default=0)
    parser.add_argument(
        "--scope",
        default="",
        help="Evaluate only one ITB scope, e.g. Fadhili_ITB, R_N_ITB, or Turkistan_ITB.",
    )
    args = parser.parse_args(argv)

    llm_selection_path = None if args.no_llm_selection else args.llm_selection
    evaluate_acc_experiment(
        ground_truth_path=args.ground_truth,
        matching_dir=args.matching_dir,
        output_dir=args.output_dir,
        llm_selection_path=llm_selection_path,
        retrieval_k=args.retrieval_k,
        cross_encoder_k=args.cross_encoder_k,
        llm_k=args.llm_k,
        scope=args.scope,
    )
    print(f"Saved ACC matching evaluation reports: {args.output_dir}")


def aggregate_final(argv: list[str] | None = None) -> None:
    """Aggregate chunk-level final selection into document-level MDL catalog and metrics."""
    parser = argparse.ArgumentParser(description="Aggregate ACC final selections to ITB document-level MDL outputs.")
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION_DIR / "acc_llm_final_selection.csv")
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BASE_DIR / "document_level")
    parser.add_argument(
        "--scope",
        default="",
        help="Aggregate/evaluate only one ITB scope, e.g. Fadhili_ITB, R_N_ITB, or Turkistan_ITB.",
    )
    args = parser.parse_args(argv)

    build_document_level_outputs(
        selection_path=args.selection,
        ground_truth_path=args.ground_truth,
        output_dir=args.output_dir,
        scope=args.scope,
    )
    print(f"Saved ACC document-level outputs: {args.output_dir}")


def _write_acc_positive_temp_csv(input_path: Path) -> Path:
    with open(input_path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = list(reader.fieldnames or [])
        rows = [row for row in reader if _is_true(row.get("Is ACC Related"))]
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8-sig", suffix=".csv", delete=False) as temp_file:
        writer = csv.DictWriter(temp_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return Path(temp_file.name)


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "yes", "y", "1"}


if __name__ == "__main__":
    evaluate_matching()
