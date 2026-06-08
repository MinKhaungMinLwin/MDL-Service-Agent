"""Command-line entrypoint for schedule output evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from evaluation_service.schedule_evaluation.service import ScheduleEvaluationService

DEFAULT_BASE_DIR = Path("output") / "current_test_env"
DEFAULT_GROUND_TRUTH_PATH = DEFAULT_BASE_DIR / "evaluation" / "ground_truth" / "all_projects_ground_truth_final.csv"
DEFAULT_CANDIDATES_PATH = (
    Path("output") / "schedule_service" / "candidates" / "mdl_candidates_output_match_all_projects_section6.csv"
)
DEFAULT_GENERATED_PATH = (
    Path("output")
    / "schedule_service"
    / "generate"
    / "generated_schedule_mdl_candidates_output_match_all_projects_section6_ntp2024-03-01.json"
)
DEFAULT_OUTPUT_DIR = DEFAULT_BASE_DIR / "evaluation" / "schedule"


def evaluate(argv: list[str] | None = None) -> None:
    """Evaluate generated schedule rows and write review reports."""
    parser = argparse.ArgumentParser(
        description="Evaluate /schedule/candidates and /schedule/generate outputs against ground truth."
    )
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--generated", type=Path, default=DEFAULT_GENERATED_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sections", nargs="+", default=("6",))
    parser.add_argument("--relevance-threshold", type=int, default=3)
    args = parser.parse_args(argv)

    ScheduleEvaluationService().evaluate(
        ground_truth_path=args.ground_truth,
        candidates_path=args.candidates,
        generated_path=args.generated,
        output_dir=args.output_dir,
        sections=tuple(str(section) for section in args.sections),
        relevance_threshold=args.relevance_threshold,
    )


if __name__ == "__main__":
    evaluate()
