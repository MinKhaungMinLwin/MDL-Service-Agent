"""Command-line entrypoint for ITB depth and keyword extraction."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from loguru import logger

from common.config import required_env
from common.openai_client import build_azure_openai_client
from common.prompts import load_prompt
from itb_service.loader import load_abbreviation_rules
from itb_service.models import ITBExtractionConfig, ITBTarget
from itb_service.prompts import DEFAULT_EXTRACTION_PROMPT_PATH, DEFAULT_VERIFICATION_PROMPT_PATH
from itb_service.service import ITBExtractionService

DEFAULT_DATA_DIR = Path("data") / "current_test_env" / "data"
DEFAULT_CHUNKS_DIR = DEFAULT_DATA_DIR / "itb_chunks"
DEFAULT_OUTPUT_DIR = Path("output") / "current_test_env" / "itb_extract"
DEFAULT_ABBREVIATION_RULES_PATH = Path("src") / "common" / "normalization_rules" / "abbreviations.json"
SECTION_CONFIG = {
    "6": {"min_page": 79, "max_page": 97},
    "7": {"min_page": 97, "max_page": 124},
}


def extract(argv: list[str] | None = None) -> None:
    """Run ITB extraction and write CSV, JSON, and token outputs."""
    parser = argparse.ArgumentParser(description="Extract ITB depth metadata from parsed chunk JSON.")
    parser.add_argument("--section", choices=sorted(SECTION_CONFIG), default=os.getenv("ITB_SECTION", "7").strip())
    parser.add_argument("--chunks-file", type=Path, default=DEFAULT_CHUNKS_DIR / "R&N_ITB_chunks.json")
    parser.add_argument("--document-name", default="R&N_ITB")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_EXTRACTION_PROMPT_PATH)
    parser.add_argument("--verify-prompt-file", type=Path, default=DEFAULT_VERIFICATION_PROMPT_PATH)
    parser.add_argument("--abbreviation-rules", type=Path, default=DEFAULT_ABBREVIATION_RULES_PATH)
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("ITB_BATCH_SIZE", "1")))
    parser.add_argument("--max-chunks", type=int, default=int(os.getenv("MAX_TEST_CHUNKS", "0")))
    parser.add_argument("--verify", action="store_true", default=_env_flag("ITB_ENABLE_LLM_VERIFY"))
    args = parser.parse_args(argv)

    section_config = SECTION_CONFIG[args.section]
    output_stem = f"output_itb_section{args.section}_focused"
    config = ITBExtractionConfig(
        model=required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        batch_size=max(1, args.batch_size),
        max_chunks=args.max_chunks,
        enable_verification=args.verify,
        requested_section=args.section,
    )
    client = build_azure_openai_client(
        api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
        default_api_version="2024-12-01-preview",
    )
    service = ITBExtractionService(
        client=client,
        config=config,
        extraction_prompt=load_prompt(args.prompt_file),
        verification_prompt=load_prompt(args.verify_prompt_file) if args.verify else "",
        abbreviation_rules=load_abbreviation_rules(args.abbreviation_rules),
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    count = service.extract_to_files(
        targets=[
            ITBTarget(
                chunks_file=args.chunks_file,
                document_name=args.document_name,
                min_page=section_config["min_page"],
                max_page=section_config["max_page"],
            )
        ],
        csv_path=args.output_dir / f"{output_stem}.csv",
        json_path=args.output_dir / f"{output_stem}.json",
        token_path=args.output_dir / f"{output_stem}_tokens.csv",
        rejected_csv_path=args.output_dir / f"{output_stem}_rejected.csv",
        rejected_json_path=args.output_dir / f"{output_stem}_rejected.json",
    )
    logger.info("Extracted {} ITB chunks for section {}", count, args.section)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "y"}


if __name__ == "__main__":
    extract()
