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


def parse_pdf(input_path: Path, max_num_pages: int | None = None) -> DoclingParseResult:
    """Parse a PDF with Docling and export JSON-ready data plus Markdown."""
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    kwargs: dict[str, Any] = {}
    if max_num_pages is not None:
        kwargs["max_num_pages"] = max_num_pages

    result = converter.convert(input_path, **kwargs)
    document = result.document

    return DoclingParseResult(
        source_path=input_path,
        document=document,
        raw_dict=document.export_to_dict(),
        markdown=document.export_to_markdown(),
        docling_version=version("docling"),
    )
