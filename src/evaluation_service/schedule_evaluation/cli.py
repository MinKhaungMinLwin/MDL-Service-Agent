"""Command-line entrypoint for schedule output evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from evaluation_service.schedule_evaluation.service import ScheduleEvaluationService
from schedule_service.candidate.candidate_extractor import DEFAULT_SCORE_THRESHOLD, DEFAULT_TOP_N

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
    parser.add_argument(
        "--matching-input",
        type=Path,
        default=None,
        help="Optional raw output_match JSON/CSV used to audit why GT pairs were dropped before candidates.",
    )
    parser.add_argument("--candidate-top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--candidate-score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
    parser.add_argument(
        "--gold-labels",
        type=Path,
        default=None,
        help="Optional schedule gold-label CSV with expected rule/activity/date fields.",
    )
    parser.add_argument(
        "--write-gold-template",
        action="store_true",
        help="Write schedule_gold_labels_template.csv for current exact-GT generated rows.",
    )
    args = parser.parse_args(argv)

    ScheduleEvaluationService().evaluate(
        ground_truth_path=args.ground_truth,
        candidates_path=args.candidates,
        generated_path=args.generated,
        output_dir=args.output_dir,
        sections=tuple(str(section) for section in args.sections),
        relevance_threshold=args.relevance_threshold,
        matching_input_path=args.matching_input,
        candidate_top_n=args.candidate_top_n,
        candidate_score_threshold=args.candidate_score_threshold,
        gold_labels_path=args.gold_labels,
        write_gold_template=args.write_gold_template,
    )


if __name__ == "__main__":
    evaluate()
