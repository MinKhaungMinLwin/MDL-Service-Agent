"""Command-line entrypoint for LLM-assisted matching ground truth."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from common.config import required_env
from common.neo4j_client import Neo4jConnection
from common.openai_client import build_azure_openai_client
from common.prompts import load_prompt
from evaluation_service.ground_truth.service import (
    DEFAULT_JUDGE_PROMPT_PATH,
    DEFAULT_VERIFY_PROMPT_PATH,
    EvaluationConfig,
    GroundTruthService,
)

DEFAULT_BASE_DIR = Path("output") / "current_test_env"
DEFAULT_EXTRACT_DIR = DEFAULT_BASE_DIR / "itb_extract"
DEFAULT_MATCHING_DIR = DEFAULT_BASE_DIR / "matching"
DEFAULT_OUTPUT_DIR = DEFAULT_BASE_DIR / "evaluation" / "ground_truth"
DEFAULT_OUTPUT_STEM = "itb_mdl_matching"
DEFAULT_CANDIDATE_SOURCE = "reference-mdl"
DEFAULT_REFERENCE_SOURCE_FILE = "R&N_MDL.xlsx"
DEFAULT_MDL_NODE_LABEL = "TestMDLDocument"


def _discover_sections(extract_dir: Path) -> tuple[str, ...]:
    prefix = "output_itb_section"
    suffix = "_focused.csv"
    sections = []
    for path in extract_dir.glob(f"{prefix}*{suffix}"):
        section = path.name.removeprefix(prefix).removesuffix(suffix)
        if section:
            sections.append(section)
    return tuple(sorted(sections, key=_section_sort_key))


def _section_sort_key(section: str) -> tuple[int, int | str]:
    return (0, int(section)) if section.isdigit() else (1, section)


def build_ground_truth(argv: list[str] | None = None) -> None:
    """Build blind pools and optionally generate LLM-assisted silver ground truth."""
    parser = argparse.ArgumentParser(
        description="Build ITB-to-MDL matching ground truth from Neo4j reference MDL or pooled retrieval outputs."
    )
    parser.add_argument("--sections", nargs="+")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["keyword", "semantic", "hybrid"],
        default=["keyword", "semantic", "hybrid"],
    )
    parser.add_argument("--extract-dir", type=Path, default=DEFAULT_EXTRACT_DIR)
    parser.add_argument("--matching-dir", type=Path, default=DEFAULT_MATCHING_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--candidate-source",
        choices=["matching-output", "reference-mdl"],
        default=DEFAULT_CANDIDATE_SOURCE,
        help="Use existing matching outputs or one reference MDL source from Neo4j.",
    )
    parser.add_argument("--reference-source-file", default=DEFAULT_REFERENCE_SOURCE_FILE)
    parser.add_argument("--mdl-node-label", default=DEFAULT_MDL_NODE_LABEL)
    parser.add_argument(
        "--reference-candidate-limit",
        type=int,
        default=int(os.getenv("ITB_EVAL_REFERENCE_CANDIDATE_LIMIT", "0")),
        help="Optional limit for reference MDL candidates. Use 0 to load all.",
    )
    parser.add_argument("--pool-top-k", type=int, default=int(os.getenv("ITB_EVAL_POOL_TOP_K", "20")))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("ITB_EVAL_BATCH_SIZE", "5")))
    parser.add_argument(
        "--judge-candidates-per-call",
        type=int,
        default=int(os.getenv("ITB_EVAL_JUDGE_CANDIDATES_PER_CALL", "25")),
    )
    parser.add_argument("--llm-retries", type=int, default=int(os.getenv("ITB_EVAL_LLM_RETRIES", "2")))
    parser.add_argument("--max-concurrency", type=int, default=int(os.getenv("ITB_EVAL_MAX_CONCURRENCY", "1")))
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--pool-only", action="store_true")
    parser.add_argument("--judge-prompt-file", type=Path, default=DEFAULT_JUDGE_PROMPT_PATH)
    parser.add_argument("--verify-prompt-file", type=Path, default=DEFAULT_VERIFY_PROMPT_PATH)
    args = parser.parse_args(argv)

    sections = tuple(args.sections) if args.sections else _discover_sections(args.extract_dir)
    if not sections:
        parser.error(f"No ITB extract files found in {args.extract_dir}")

    stem = DEFAULT_OUTPUT_STEM
    pool_path = args.output_dir / f"{stem}_candidate_pool.json"
    config_options = {
        "sections": sections,
        "modes": tuple(args.modes),
        "pool_top_k": args.pool_top_k,
        "batch_size": args.batch_size,
        "judge_candidates_per_call": args.judge_candidates_per_call,
        "llm_retries": args.llm_retries,
        "max_concurrency": args.max_concurrency,
        "verify": args.verify,
        "resume": args.resume,
    }
    if args.pool_only:
        config = EvaluationConfig(model="pool-only", **config_options)
        service = GroundTruthService(config, client=None, judge_prompt="")
        if args.candidate_source == "reference-mdl":
            with Neo4jConnection() as conn:
                service.build_reference_pool(
                    args.extract_dir,
                    conn,
                    pool_path,
                    args.reference_source_file,
                    args.mdl_node_label,
                    args.reference_candidate_limit,
                )
        else:
            service.build_pool(args.extract_dir, args.matching_dir, pool_path)
        return

    config = EvaluationConfig(model=required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"), **config_options)
    service = GroundTruthService(
        config=config,
        client=build_azure_openai_client(
            api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
            default_api_version="2024-12-01-preview",
        ),
        judge_prompt=load_prompt(args.judge_prompt_file),
        verify_prompt=load_prompt(args.verify_prompt_file) if args.verify else "",
    )
    if args.candidate_source == "reference-mdl":
        with Neo4jConnection() as conn:
            pools = service.build_reference_pool(
                args.extract_dir,
                conn,
                pool_path,
                args.reference_source_file,
                args.mdl_node_label,
                args.reference_candidate_limit,
            )
    else:
        pools = service.build_pool(args.extract_dir, args.matching_dir, pool_path)
    service.judge_to_files(
        pools=pools,
        judgments_path=args.output_dir / f"{stem}_llm_judgments.json",
        verifications_path=args.output_dir / f"{stem}_llm_verifications.json",
        ground_truth_path=args.output_dir / f"{stem}_ground_truth.csv",
        high_precision_path=args.output_dir / f"{stem}_ground_truth_high_precision.csv" if args.verify else None,
    )


if __name__ == "__main__":
    build_ground_truth()
