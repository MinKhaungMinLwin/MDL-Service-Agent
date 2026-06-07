"""Command-line entrypoint for LLM-assisted matching ground truth."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from common.config import required_env
from common.openai_client import build_azure_openai_client
from common.prompts import load_prompt
from evaluation_service.ground_truth.acc_itb_mdl import (
    DEFAULT_ACC_SELECT_PROMPT_PATH,
    DEFAULT_ACC_VERIFY_PROMPT_PATH,
    ACCGroundTruthConfig,
    ACCGroundTruthService,
)
from evaluation_service.ground_truth.service import (
    DEFAULT_POSITIVE_JUDGE_PROMPT_PATH,
    DEFAULT_VERIFY_PROMPT_PATH,
    EvaluationConfig,
    GroundTruthService,
    build_verified_positive_ground_truth_rows,
    write_merged_positive_ground_truth_rows,
)

DEFAULT_BASE_DIR = Path("output") / "current_test_env"
DEFAULT_EXTRACT_DIR = DEFAULT_BASE_DIR / "itb_extract"
DEFAULT_MATCHING_DIR = DEFAULT_BASE_DIR / "matching"
DEFAULT_OUTPUT_DIR = DEFAULT_BASE_DIR / "evaluation" / "ground_truth"
DEFAULT_OUTPUT_STEM = "itb_mdl_matching"
DEFAULT_FINAL_GROUND_TRUTH_PATH = DEFAULT_OUTPUT_DIR / f"{DEFAULT_OUTPUT_STEM}_ground_truth_final.csv"
DEFAULT_ACC_EXPERIMENT_DIR = DEFAULT_BASE_DIR / "acc_experiment"
DEFAULT_ACC_MDL_CATALOG_PATH = DEFAULT_ACC_EXPERIMENT_DIR / "mdl_filter" / "acc_mdl_catalog.csv"
DEFAULT_ACC_ITB_FILTER_DIR = DEFAULT_ACC_EXPERIMENT_DIR / "itb_filter"
DEFAULT_ACC_GROUND_TRUTH_DIR = DEFAULT_ACC_EXPERIMENT_DIR / "ground_truth"


def _discover_sections(extract_dir: Path) -> tuple[str, ...]:
    prefix = "itb_extraction_section"
    suffix = ".csv"
    sections = []
    for path in extract_dir.glob(f"{prefix}*{suffix}"):
        section = path.name.removeprefix(prefix).removesuffix(suffix)
        if section:
            sections.append(section)
    return tuple(sorted(sections, key=_section_sort_key))


def _section_sort_key(section: str) -> tuple[int, int | str]:
    return (0, int(section)) if section.isdigit() else (1, section)


def build_ground_truth(argv: list[str] | None = None) -> None:
    """Build LLM-assisted matching ground truth from matching outputs."""
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
    parser.add_argument("--llm-retries", type=int, default=int(os.getenv("ITB_EVAL_LLM_RETRIES", "2")))
    parser.add_argument("--max-concurrency", type=int, default=int(os.getenv("ITB_EVAL_MAX_CONCURRENCY", "1")))
    parser.add_argument(
        "--max-itb-chunks",
        type=int,
        default=int(os.getenv("ITB_EVAL_MAX_ITB_CHUNKS", "0")),
        help="Limit the number of ITB chunks for quick test runs. Use 0 to process all chunks.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--judge-prompt-file", type=Path, default=DEFAULT_POSITIVE_JUDGE_PROMPT_PATH)
    parser.add_argument("--verify-prompt-file", type=Path, default=DEFAULT_VERIFY_PROMPT_PATH)
    parser.add_argument(
        "--final-ground-truth",
        type=Path,
        default=None,
        help="Canonical positive ground-truth CSV to update after verification.",
    )
    args = parser.parse_args(argv)

    sections = tuple(args.sections) if args.sections else _discover_sections(args.extract_dir)
    if not sections:
        parser.error(f"No ITB extract files found in {args.extract_dir}")

    stem = DEFAULT_OUTPUT_STEM
    config_options = {
        "sections": sections,
        "modes": tuple(args.modes),
        "llm_retries": args.llm_retries,
        "max_concurrency": args.max_concurrency,
        "max_itb_chunks": args.max_itb_chunks,
        "resume": args.resume,
    }

    config = EvaluationConfig(model=required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"), **config_options)
    service = GroundTruthService(
        config=config,
        client=build_azure_openai_client(
            api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
            default_api_version="2024-12-01-preview",
        ),
        judge_prompt=load_prompt(args.judge_prompt_file),
        verify_prompt=load_prompt(args.verify_prompt_file),
    )
    pools = service.build_pool(args.extract_dir, args.matching_dir)
    judgments, verifications = service.judge(
        pools=pools,
        resume_state_path=args.output_dir / f"{stem}_ground_truth_resume_state.csv" if args.resume else None,
    )
    final_path = args.final_ground_truth or args.output_dir / f"{stem}_ground_truth_final.csv"
    positive_rows = build_verified_positive_ground_truth_rows(judgments, verifications)
    count = merge_positive_ground_truth(final_path, positive_rows)
    print(f"Saved {count} final positive ground-truth rows: {final_path}")


def merge_positive_ground_truth(final_path: Path, rows: list[dict]) -> int:
    """Merge new verified positives into the canonical final ground truth."""
    return write_merged_positive_ground_truth_rows(final_path, rows)


def build_acc_ground_truth(argv: list[str] | None = None) -> None:
    """Build ACC experiment ground truth from filtered ITB chunks and ACC MDL catalog."""
    parser = argparse.ArgumentParser(
        description="Build ACC ITB-to-MDL ground truth from filtered ACC experiment CSV outputs."
    )
    parser.add_argument("--mdl-catalog", type=Path, default=DEFAULT_ACC_MDL_CATALOG_PATH)
    parser.add_argument("--itb-filter-dir", type=Path, default=DEFAULT_ACC_ITB_FILTER_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ACC_GROUND_TRUTH_DIR)
    parser.add_argument("--scope", action="append", dest="scopes", help="ITB filter scope folder name to process.")
    parser.add_argument("--select-prompt-file", type=Path, default=DEFAULT_ACC_SELECT_PROMPT_PATH)
    parser.add_argument("--verify-prompt-file", type=Path, default=DEFAULT_ACC_VERIFY_PROMPT_PATH)
    parser.add_argument("--model", default=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"))
    parser.add_argument("--llm-retries", type=int, default=int(os.getenv("ACC_GT_LLM_RETRIES", "2")))
    parser.add_argument(
        "--max-itb-chunks",
        type=int,
        default=int(os.getenv("ACC_GT_MAX_ITB_CHUNKS", "0")),
        help="Limit ITB chunks for a quick test run. Use 0 to process all chunks.",
    )
    args = parser.parse_args(argv)

    config = ACCGroundTruthConfig(
        model=args.model or required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        llm_retries=args.llm_retries,
        max_itb_chunks=args.max_itb_chunks,
    )
    service = ACCGroundTruthService(
        config=config,
        client=build_azure_openai_client(
            api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
            default_api_version="2024-12-01-preview",
            timeout=1200.0,
        ),
        select_prompt=load_prompt(args.select_prompt_file),
        verify_prompt=load_prompt(args.verify_prompt_file),
    )
    count = service.build(
        mdl_catalog_path=args.mdl_catalog,
        itb_filter_dir=args.itb_filter_dir,
        output_dir=args.output_dir,
        scopes=args.scopes,
    )
    print(f"Saved {count} ACC ground-truth rows: {args.output_dir / 'acc_itb_mdl_ground_truth.csv'}")


if __name__ == "__main__":
    build_ground_truth()
