from __future__ import annotations

import argparse
import json
from pathlib import Path

from loguru import logger

from parser_service.docling_parser import parse_pdf


def main() -> None:
    args = _parse_args()
    input_path = args.input.resolve()
    output_dir = (args.output or Path("parser_service") / "outputs" / input_path.stem).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Parsing PDF: {}", input_path)
    docling_result = parse_pdf(input_path, max_num_pages=args.max_pages)

    logger.info("Writing parser outputs to {}", output_dir)
    _write_json(output_dir / "docling.json", docling_result.raw_dict)
    _write_text(output_dir / "docling.md", docling_result.markdown)

    logger.success("Parsed: {}", input_path)
    logger.info("Output: {}", output_dir)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a PDF with Docling.")
    parser.add_argument("--input", required=True, type=Path, help="Path to the source PDF.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output folder. Defaults to parser_service/outputs/<input-stem>.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional page limit for quick parser smoke tests.",
    )
    return parser.parse_args()


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
