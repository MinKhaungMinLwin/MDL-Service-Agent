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
    DEFAULT_AUDIT_PROMPT_PATH,
    DEFAULT_JUDGE_PROMPT_PATH,
    DEFAULT_POSITIVE_JUDGE_PROMPT_PATH,
    DEFAULT_VERIFY_PROMPT_PATH,
    AuditConfig,
    EvaluationConfig,
    GroundTruthAuditService,
    GroundTruthService,
    MDLGroundTruthRepository,
    build_verified_positive_ground_truth_rows,
    write_merged_positive_ground_truth_rows,
)

DEFAULT_BASE_DIR = Path("output") / "current_test_env"
DEFAULT_EXTRACT_DIR = DEFAULT_BASE_DIR / "itb_extract"
DEFAULT_MATCHING_DIR = DEFAULT_BASE_DIR / "matching"
DEFAULT_OUTPUT_DIR = DEFAULT_BASE_DIR / "evaluation" / "ground_truth"
DEFAULT_OUTPUT_STEM = "itb_mdl_matching"
DEFAULT_FINAL_GROUND_TRUTH_PATH = DEFAULT_OUTPUT_DIR / f"{DEFAULT_OUTPUT_STEM}_ground_truth_final.csv"
DEFAULT_AUDIT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / f"{DEFAULT_OUTPUT_STEM}_ground_truth_audit.csv"
DEFAULT_SUSPICIOUS_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / f"{DEFAULT_OUTPUT_STEM}_ground_truth_suspicious.csv"


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
    verify_group = parser.add_mutually_exclusive_group()
    verify_group.add_argument(
        "--verify",
        dest="verify",
        action="store_true",
        default=True,
        help="Verify LLM judgments and write the verified ground-truth file. Enabled by default.",
    )
    verify_group.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        help="Skip verification and write the unverified silver ground-truth file.",
    )
    parser.add_argument("--resume", action="store_true")
    judge_mode_group = parser.add_mutually_exclusive_group()
    judge_mode_group.add_argument(
        "--positive-only",
        dest="positive_only",
        action="store_true",
        default=True,
        help="Ask the judge to return only direct positive matches. Enabled by default.",
    )
    judge_mode_group.add_argument(
        "--full-judgment",
        dest="positive_only",
        action="store_false",
        help="Judge every candidate with a 0-3 relevance score.",
    )
    parser.add_argument("--judge-prompt-file", type=Path)
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
        "pool_top_k": args.pool_top_k,
        "batch_size": args.batch_size,
        "judge_candidates_per_call": args.judge_candidates_per_call,
        "llm_retries": args.llm_retries,
        "max_concurrency": args.max_concurrency,
        "max_itb_chunks": args.max_itb_chunks,
        "verify": args.verify,
        "positive_only": args.positive_only,
        "resume": args.resume,
    }
    judge_prompt_path = args.judge_prompt_file or (
        DEFAULT_POSITIVE_JUDGE_PROMPT_PATH if args.positive_only else DEFAULT_JUDGE_PROMPT_PATH
    )

    config = EvaluationConfig(model=required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"), **config_options)
    service = GroundTruthService(
        config=config,
        client=build_azure_openai_client(
            api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
            default_api_version="2024-12-01-preview",
        ),
        judge_prompt=load_prompt(judge_prompt_path),
        verify_prompt=load_prompt(args.verify_prompt_file) if args.verify else "",
    )
    pools = service.build_pool(args.extract_dir, args.matching_dir)
    judgments, verifications = service.judge(
        pools=pools,
        resume_state_path=args.output_dir / f"{stem}_ground_truth_resume_state.json" if args.resume else None,
    )
    if args.verify:
        final_path = args.final_ground_truth or args.output_dir / f"{stem}_ground_truth_final.csv"
        positive_rows = build_verified_positive_ground_truth_rows(judgments, verifications)
        count = merge_positive_ground_truth(final_path, positive_rows)
        print(f"Saved {count} final positive ground-truth rows: {final_path}")


def merge_positive_ground_truth(final_path: Path, rows: list[dict]) -> int:
    """Merge new verified positives into the canonical final ground truth."""
    return write_merged_positive_ground_truth_rows(final_path, rows)


def audit_ground_truth(argv: list[str] | None = None) -> None:
    """Audit final ITB-to-MDL matching ground truth with an LLM."""
    parser = argparse.ArgumentParser(description="Audit final ITB-to-MDL matching ground truth.")
    parser.add_argument("--sections", nargs="+")
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_FINAL_GROUND_TRUTH_PATH)
    parser.add_argument("--extract-dir", type=Path, default=DEFAULT_EXTRACT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_AUDIT_OUTPUT_PATH)
    parser.add_argument(
        "--audited-ground-truth",
        type=Path,
        default=None,
        help="Write audit_status=ok rows to this CSV. Defaults to overwriting --ground-truth.",
    )
    parser.add_argument(
        "--suspicious-output",
        type=Path,
        default=DEFAULT_SUSPICIOUS_OUTPUT_PATH,
        help="Write audit_status=suspicious rows to a separate review CSV.",
    )
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("ITB_EVAL_AUDIT_BATCH_SIZE", "5")))
    parser.add_argument("--llm-retries", type=int, default=int(os.getenv("ITB_EVAL_LLM_RETRIES", "2")))
    parser.add_argument("--max-concurrency", type=int, default=int(os.getenv("ITB_EVAL_MAX_CONCURRENCY", "1")))
    parser.add_argument(
        "--max-rows",
        type=int,
        default=int(os.getenv("ITB_EVAL_AUDIT_MAX_ROWS", "0")),
        help="Limit the number of ground-truth rows for quick audit runs. Use 0 to process all rows.",
    )
    parser.add_argument("--node-label", default=os.getenv("MDL_NEO4J_NODE_LABEL", "TestMDLDocument"))
    parser.add_argument("--audit-prompt-file", type=Path, default=DEFAULT_AUDIT_PROMPT_PATH)
    args = parser.parse_args(argv)

    sections = tuple(args.sections) if args.sections else _discover_sections(args.extract_dir)
    if not sections:
        parser.error(f"No ITB extract files found in {args.extract_dir}")

    config = AuditConfig(
        model=required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        sections=sections,
        batch_size=args.batch_size,
        llm_retries=args.llm_retries,
        max_concurrency=args.max_concurrency,
        max_rows=args.max_rows,
        node_label=args.node_label,
    )
    with Neo4jConnection() as conn:
        service = GroundTruthAuditService(
            config=config,
            client=build_azure_openai_client(
                api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
                default_api_version="2024-12-01-preview",
            ),
            repository=MDLGroundTruthRepository(conn, config.node_label),
            audit_prompt=load_prompt(args.audit_prompt_file),
        )
        service.audit_to_file(
            ground_truth_path=args.ground_truth,
            extract_dir=args.extract_dir,
            output_path=args.output,
            audited_ground_truth_path=args.audited_ground_truth or args.ground_truth,
            suspicious_path=args.suspicious_output,
        )


if __name__ == "__main__":
    build_ground_truth()
