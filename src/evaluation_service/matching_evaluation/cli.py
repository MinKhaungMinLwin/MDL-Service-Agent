"""Command-line entrypoint for ITB-to-MDL matching evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from evaluation_service.matching_evaluation.loaders import discover_modes, discover_sections
from evaluation_service.matching_evaluation.service import MatchingEvaluationService

DEFAULT_BASE_DIR = Path("output") / "current_test_env"
DEFAULT_GROUND_TRUTH_PATH = (
    DEFAULT_BASE_DIR / "evaluation" / "ground_truth" / "itb_mdl_matching_ground_truth_final.csv"
)
DEFAULT_MATCHING_DIR = DEFAULT_BASE_DIR / "matching"
DEFAULT_OUTPUT_DIR = DEFAULT_BASE_DIR / "evaluation" / "matching"


def evaluate(argv: list[str] | None = None) -> None:
    """Evaluate ITB-to-MDL matching outputs against ground truth."""
    parser = argparse.ArgumentParser(description="Evaluate ITB-to-MDL matching quality against ground truth.")
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    parser.add_argument("--matching-dir", type=Path, default=DEFAULT_MATCHING_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--modes", nargs="+", choices=["keyword", "semantic", "hybrid"])
    parser.add_argument("--sections", nargs="+")
    args = parser.parse_args(argv)

    modes = tuple(args.modes) if args.modes else discover_modes(args.matching_dir)
    sections = tuple(args.sections) if args.sections else discover_sections(args.matching_dir, modes)
    MatchingEvaluationService().evaluate(
        ground_truth_path=args.ground_truth,
        matching_dir=args.matching_dir,
        output_dir=args.output_dir,
        modes=modes,
        sections=sections,
    )


if __name__ == "__main__":
    evaluate()
