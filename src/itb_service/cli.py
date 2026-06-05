"""Command-line entrypoint for ITB depth and keyword extraction."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from loguru import logger

from common.config import load_env_file, required_env
from common.openai_client import build_azure_openai_client
from common.prompts import load_prompt
from itb_service.loader import clean_chunk_document, load_abbreviation_rules
from itb_service.models import ITBExtractionConfig, ITBTarget
from itb_service.prompts import DEFAULT_EXTRACTION_PROMPT_PATH, DEFAULT_VERIFICATION_PROMPT_PATH
from itb_service.service import ITBExtractionService

DEFAULT_DATA_DIR = Path("data") / "current_test_env" / "data"
DEFAULT_CHUNKS_DIR = DEFAULT_DATA_DIR / "itb_chunks"
DEFAULT_OUTPUT_DIR = Path("output") / "current_test_env" / "itb_extract"
DEFAULT_ABBREVIATION_RULES_PATH = Path("src") / "common" / "normalization_rules" / "abbreviations.json"
DEFAULT_CHUNKS_FILE = DEFAULT_CHUNKS_DIR / "R&N_ITB_chunks.json"
SECTION_CONFIG = {
    "6": {"min_page": 79, "max_page": 97},
    "7": {"min_page": 97, "max_page": 124},
}


def extract(argv: list[str] | None = None) -> None:
    """Run ITB extraction and write CSV, JSON, and token outputs."""
    load_env_file()
    parser = argparse.ArgumentParser(description="Extract ITB depth metadata from parsed chunk JSON.")
    parser.add_argument(
        "--mode",
        choices=["all", "section"],
        default=os.getenv("ITB_EXTRACT_MODE", "section").strip().lower(),
        help="Use 'all' to extract every chunk, or 'section' to use configured page ranges.",
    )
    parser.add_argument(
        "--sections",
        default=os.getenv("ITB_SECTIONS", "7"),
        help="Comma-separated sections for section mode.",
    )
    parser.add_argument("--chunks-file", action="append", type=Path, dest="chunks_files")
    parser.add_argument("--chunks-dir", type=Path, default=Path(os.getenv("ITB_CHUNKS_DIR", DEFAULT_CHUNKS_DIR)))
    parser.add_argument("--document-name", default=os.getenv("ITB_DOCUMENT_NAME", ""))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("ITB_EXTRACT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)),
    )
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_EXTRACTION_PROMPT_PATH)
    parser.add_argument("--verify-prompt-file", type=Path, default=DEFAULT_VERIFICATION_PROMPT_PATH)
    parser.add_argument("--abbreviation-rules", type=Path, default=DEFAULT_ABBREVIATION_RULES_PATH)
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("ITB_BATCH_SIZE", "1")))
    parser.add_argument("--max-chunks", type=int, default=int(os.getenv("MAX_TEST_CHUNKS", "0")))
    parser.add_argument("--verify", action="store_true", default=_env_flag("ITB_ENABLE_LLM_VERIFY"))
    args = parser.parse_args(argv)

    sections = _resolve_sections(args.mode, args.sections)
    chunks_files = _resolve_chunks_files(args.chunks_files, args.chunks_dir, args.mode)
    model = required_env("AZURE_OPENAI_CHAT_DEPLOYMENT")
    client = build_azure_openai_client(
        api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
        default_api_version="2024-12-01-preview",
    )
    extraction_prompt = load_prompt(args.prompt_file)
    verification_prompt = load_prompt(args.verify_prompt_file) if args.verify else ""
    abbreviation_rules = load_abbreviation_rules(args.abbreviation_rules)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    total_count = 0
    for chunks_file in chunks_files:
        document_name = args.document_name or _infer_document_name(chunks_file)
        output_dir = args.output_dir / _safe_scope_name(document_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        for section in sections:
            config = ITBExtractionConfig(
                model=model,
                batch_size=max(1, args.batch_size),
                max_chunks=args.max_chunks,
                enable_verification=args.verify,
                requested_section="" if args.mode == "all" else section,
            )
            service = ITBExtractionService(
                client=client,
                config=config,
                extraction_prompt=extraction_prompt,
                verification_prompt=verification_prompt,
                abbreviation_rules=abbreviation_rules,
            )
            target = _build_target(chunks_file, document_name, args.mode, section)
            output_stem = "output_itb_all_focused" if args.mode == "all" else f"output_itb_section{section}_focused"
            count = service.extract_to_files(
                targets=[target],
                csv_path=output_dir / f"{output_stem}.csv",
                json_path=output_dir / f"{output_stem}.json",
                token_path=output_dir / f"{output_stem}_tokens.csv",
                rejected_csv_path=output_dir / f"{output_stem}_rejected.csv",
                rejected_json_path=output_dir / f"{output_stem}_rejected.json",
            )
            total_count += count
            logger.info(
                "Extracted {} ITB chunks from {} ({})",
                count,
                chunks_file,
                "all chunks" if args.mode == "all" else f"section {section}",
            )
    logger.info("Extracted {} ITB chunks total", total_count)


def clean_chunks(argv: list[str] | None = None) -> None:
    """Clean parsed ITB chunk JSON files and write reviewable JSON artifacts."""
    load_env_file()
    parser = argparse.ArgumentParser(description="Clean parsed ITB chunk JSON files before ITB extraction.")
    parser.add_argument("--chunks-file", action="append", type=Path, dest="chunks_files")
    parser.add_argument("--chunks-dir", type=Path, default=Path(os.getenv("ITB_CHUNKS_DIR", DEFAULT_CHUNKS_DIR)))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    chunks_files = _resolve_chunks_files(args.chunks_files, args.chunks_dir, mode="all")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for chunks_file in chunks_files:
        data = json.loads(chunks_file.read_text(encoding="utf-8"))
        original_count = len(data.get("chunks", []))
        cleaned_data = clean_chunk_document(data)
        cleaned_count = len(cleaned_data.get("chunks", []))
        output_path = args.output_dir / chunks_file.name
        output_path.write_text(json.dumps(cleaned_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.info(
            "Cleaned {}: kept {} of {} chunks -> {}",
            chunks_file,
            cleaned_count,
            original_count,
            output_path,
        )


def _resolve_chunks_files(cli_files: list[Path] | None, chunks_dir: Path, mode: str) -> list[Path]:
    if cli_files:
        return cli_files
    env_files = _split_env_list(os.getenv("ITB_CHUNKS_FILES", ""))
    if env_files:
        return [Path(value) for value in env_files]
    if mode == "all":
        return sorted(chunks_dir.glob("*_chunks.json"))
    return [DEFAULT_CHUNKS_FILE]


def _resolve_sections(mode: str, sections: str) -> list[str]:
    if mode == "all":
        return ["all"]
    resolved = _split_env_list(sections.replace(",", ";"))
    unknown_sections = [value for value in resolved if value not in SECTION_CONFIG]
    if unknown_sections:
        raise ValueError(f"Unknown ITB section(s): {', '.join(unknown_sections)}")
    return resolved


def _build_target(chunks_file: Path, document_name: str, mode: str, section: str) -> ITBTarget:
    if mode == "all":
        return ITBTarget(chunks_file=chunks_file, document_name=document_name)
    section_config = SECTION_CONFIG[section]
    return ITBTarget(
        chunks_file=chunks_file,
        document_name=document_name,
        min_page=section_config["min_page"],
        max_page=section_config["max_page"],
    )


def _split_env_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def _infer_document_name(chunks_file: Path) -> str:
    stem = chunks_file.stem
    for suffix in ("_chunks", " chunks"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem.replace(" ", "_")


def _safe_scope_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_") or "itb"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "y"}


if __name__ == "__main__":
    extract()
