"""Extract ITB chunk metadata and retrieval queries with Azure OpenAI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger
from mdl_runtime.config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_CHAT_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    BASE_DIR,
    OUTPUT_DIR,
    REPO_ROOT,
    required,
)
from openai import AzureOpenAI

sys.path.append(str(REPO_ROOT / "src"))

from itb_service.loader import load_abbreviation_rules
from itb_service.models import ITBExtractionConfig, ITBTarget
from itb_service.prompts import load_prompt
from itb_service.service import ITBExtractionService

SCRIPT_DIR = Path(__file__).resolve().parent
PROMPT_FILE = SCRIPT_DIR / "prompts" / "itb_keyword_extraction_v2.md"
VERIFY_PROMPT_FILE = SCRIPT_DIR / "prompts" / "itb_depth_verification.md"
ABBREVIATION_RULES_PATH = REPO_ROOT / "src" / "common" / "normalization_rules" / "abbreviations.json"
CHUNKS_DIR = BASE_DIR / "data" / "itb_chunks"
SECTION_CONFIG = {
    "6": {"min_page": 79, "max_page": 97},
    "7": {"min_page": 97, "max_page": 124},
}


def main() -> None:
    """Run ITB extraction for the configured R&N ITB section."""
    section = os.getenv("ITB_SECTION", "7").strip()
    if section not in SECTION_CONFIG:
        raise ValueError("ITB_SECTION must be 6 or 7")
    section_config = SECTION_CONFIG[section]
    output_stem = f"output_itb_section{section}_focused"
    enable_verification = _env_flag("ITB_ENABLE_LLM_VERIFY")
    config = ITBExtractionConfig(
        model=AZURE_OPENAI_CHAT_DEPLOYMENT,
        batch_size=max(1, int(os.getenv("ITB_BATCH_SIZE", "1"))),
        max_chunks=int(os.getenv("MAX_TEST_CHUNKS", "0")),
        enable_verification=enable_verification,
    )
    client = AzureOpenAI(
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=required(AZURE_OPENAI_API_KEY, "AZURE_OPENAI_API_KEY"),
    )
    service = ITBExtractionService(
        client=client,
        config=config,
        extraction_prompt=load_prompt(PROMPT_FILE),
        verification_prompt=load_prompt(VERIFY_PROMPT_FILE) if enable_verification else "",
        abbreviation_rules=load_abbreviation_rules(ABBREVIATION_RULES_PATH),
    )
    target = ITBTarget(
        chunks_file=CHUNKS_DIR / "R&N_ITB_chunks.json",
        document_name="R&N_ITB",
        min_page=section_config["min_page"],
        max_page=section_config["max_page"],
    )
    count = service.extract_to_files(
        targets=[target],
        csv_path=OUTPUT_DIR / f"{output_stem}.csv",
        json_path=OUTPUT_DIR / f"{output_stem}.json",
        token_path=OUTPUT_DIR / "output_itb_tokens.csv",
    )
    logger.info("Extracted {} ITB chunks for section {}", count, section)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "y"}


if __name__ == "__main__":
    main()
