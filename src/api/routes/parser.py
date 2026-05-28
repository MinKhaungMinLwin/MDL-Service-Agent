"""Parser service API routes."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from loguru import logger

try:
    from parser_service.service import ParserOutput, parse_pdf_to_output
except ImportError:
    ParserOutput = object
    parse_pdf_to_output = None


router = APIRouter(tags=["parser"])

UPLOAD_DIR = Path("output") / "parser_service" / "uploads"
OUTPUT_DIR = Path("output") / "parser_service" / "parsed"
PreviewPages = Annotated[int | None, Query(gt=0)]


@router.post("/parse")
def parse(file: Annotated[UploadFile, File(...)], preview_pages: PreviewPages = None) -> dict[str, object]:
    """Parse an uploaded PDF and return output file metadata."""
    if parse_pdf_to_output is None:
        raise HTTPException(status_code=503, detail="Parser service is not available.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    input_path = UPLOAD_DIR / Path(file.filename or "upload.pdf").name

    logger.info("Received PDF upload: {}", input_path.name)
    with input_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    parser_output = parse_pdf_to_output(
        input_path=input_path,
        output_dir=OUTPUT_DIR / input_path.stem,
        preview_pages=preview_pages,
    )
    return _response(parser_output)


def _response(parser_output: ParserOutput) -> dict[str, object]:
    """Build the API response for a parser output."""
    return {
        "document_id": parser_output.document_id,
        "input_path": str(parser_output.input_path),
        "output_dir": str(parser_output.output_dir),
        "docling_version": parser_output.docling_version,
        "files": {
            "json": str(parser_output.json_path),
            "markdown": str(parser_output.markdown_path),
        },
    }

