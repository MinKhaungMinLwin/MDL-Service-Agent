"""Command-line entrypoint for LLM-assisted matching ground truth."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from common.config import required_env
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
        description="Build ITB-to-MDL matching ground truth from global matching outputs."
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
    parser.add_argument("--pool-top-k", type=int, default=int(os.getenv("ITB_EVAL_POOL_TOP_K", "20")))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("ITB_EVAL_BATCH_SIZE", "5")))
    parser.add_argument(
        "--judge-candidates-per-call",
        type=int,
        default=int(os.getenv("ITB_EVAL_JUDGE_CANDIDATES_PER_CALL", "25")),
    )
    parser.add_argument("--llm-retries", type=int, default=int(os.getenv("ITB_EVAL_LLM_RETRIES", "2")))
    parser.add_argument("--max-concurrency", type=int, default=int(os.getenv("ITB_EVAL_MAX_CONCURRENCY", "1")))
    parser.add_argument(
        "--max-itb-chunks",
        type=int,
        default=int(os.getenv("ITB_EVAL_MAX_ITB_CHUNKS", "0")),
        help="Limit the number of ITB chunks for quick test runs. Use 0 to process all chunks.",
    )
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
    pool_path = args.output_dir / f"{stem}_candidate_pool.json" if args.pool_only else None
    config_options = {
        "sections": sections,
        "modes": tuple(args.modes),
        "pool_top_k": args.pool_top_k,
        "batch_size": args.batch_size,
        "judge_candidates_per_call": args.judge_candidates_per_call,
        "llm_retries": args.llm_retries,
        "max_concurrency": args.max_concurrency,
        "max_itb_chunks": args.max_itb_chunks,
        "verify": args.verify,
        "resume": args.resume,
    }
    if args.pool_only:
        config = EvaluationConfig(model="pool-only", **config_options)
        service = GroundTruthService(
            config,
            client=None,
            judge_prompt="",
        )
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
    pools = service.build_pool(args.extract_dir, args.matching_dir, pool_path)
    service.judge_to_files(
        pools=pools,
        resume_state_path=args.output_dir / f"{stem}_ground_truth_resume_state.json" if args.resume else None,
        ground_truth_path=None if args.verify else args.output_dir / f"{stem}_ground_truth.csv",
        positive_path=args.output_dir / f"{stem}_ground_truth_positive.csv" if args.verify else None,
        negative_path=args.output_dir / f"{stem}_ground_truth_negative.csv" if args.verify else None,
        verified_path=args.output_dir / f"{stem}_ground_truth_verified.csv" if args.verify else None,
    )


if __name__ == "__main__":
    build_ground_truth()
