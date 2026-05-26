from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from parser_service.docling_parser import parse_pdf


@dataclass(frozen=True)
class ParserOutput:
    document_id: str
    input_path: Path
    output_dir: Path
    json_path: Path
    markdown_path: Path
    docling_version: str | None


def parse_pdf_to_output(
    input_path: Path,
    output_dir: Path | None = None,
    max_num_pages: int | None = None,
) -> ParserOutput:
    resolved_input = input_path.resolve()
    resolved_output = (output_dir or Path("output") / "parser_service" / "parsed" / resolved_input.stem).resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)

    logger.info("Parsing PDF: {}", resolved_input)
    docling_result = parse_pdf(resolved_input, max_num_pages=max_num_pages)

    json_path = resolved_output / "docling.json"
    markdown_path = resolved_output / "docling.md"

    logger.info("Writing parser outputs to {}", resolved_output)
    json_path.write_text(json.dumps(docling_result.raw_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(docling_result.markdown, encoding="utf-8")

    return ParserOutput(
        document_id=resolved_input.stem,
        input_path=resolved_input,
        output_dir=resolved_output,
        json_path=json_path,
        markdown_path=markdown_path,
        docling_version=docling_result.docling_version,
    )
