"""Docling wrapper for parsing PDF documents."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DoclingParseResult:
    """Parsed Docling document and exported representations."""

    source_path: Path
    document: Any
    raw_dict: dict[str, Any]
    markdown: str
    docling_version: str | None


def parse_pdf(input_path: Path) -> DoclingParseResult:
    """Parse a PDF with Docling and export JSON-ready data plus Markdown."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions(do_ocr=False)
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})
    result = converter.convert(input_path)
    document = result.document

    return DoclingParseResult(
        source_path=input_path,
        document=document,
        raw_dict=document.export_to_dict(),
        markdown=document.export_to_markdown(),
        docling_version=version("docling"),
    )
