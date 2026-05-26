"""Application service for writing parsed PDF outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from pypdf import PdfReader, PdfWriter

from parser_service.docling_parser import parse_pdf


@dataclass(frozen=True)
class ParserOutput:
    """File locations produced by a parser run."""

    document_id: str
    input_path: Path
    output_dir: Path
    json_path: Path
    markdown_path: Path
    docling_version: str | None


def parse_pdf_to_output(
    input_path: Path,
    output_dir: Path | None = None,
    preview_pages: int | None = None,
) -> ParserOutput:
    """Parse a PDF and write Docling JSON and Markdown outputs."""
    source_input = input_path
    output_path = output_dir or Path("output") / "parser_service" / "parsed" / source_input.stem
    resolved_output = output_path.resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    parser_input = _preview_pdf(source_input, output_path, preview_pages) if preview_pages else source_input

    logger.info("Parsing PDF: {}", parser_input)
    docling_result = parse_pdf(parser_input)

    json_path = resolved_output / "docling.json"
    markdown_path = resolved_output / "docling.md"

    logger.info("Writing parser outputs to {}", resolved_output)
    json_path.write_text(json.dumps(docling_result.raw_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(docling_result.markdown, encoding="utf-8")

    return ParserOutput(
        document_id=source_input.stem,
        input_path=source_input,
        output_dir=resolved_output,
        json_path=json_path,
        markdown_path=markdown_path,
        docling_version=docling_result.docling_version,
    )


def _preview_pdf(input_path: Path, output_dir: Path, preview_pages: int) -> Path:
    """Write a temporary PDF containing the first preview pages."""
    reader = PdfReader(input_path)
    writer = PdfWriter()

    for page in reader.pages[:preview_pages]:
        writer.add_page(page)

    preview_path = output_dir / f"{input_path.stem}_first_{preview_pages}_pages.pdf"
    with preview_path.open("wb") as buffer:
        writer.write(buffer)

    return preview_path
