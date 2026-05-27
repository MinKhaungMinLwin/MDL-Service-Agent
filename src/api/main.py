"""FastAPI entrypoint for the PDF parser service."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Query, UploadFile
from loguru import logger

from chunker_service.service import ChunkerOutput, chunk_docling_json_to_output
from parser_service.service import ParserOutput, parse_pdf_to_output

app = FastAPI(title="Doosan MDL API")

UPLOAD_DIR = Path("output") / "parser_service" / "uploads"
OUTPUT_DIR = Path("output") / "parser_service" / "parsed"
CHUNK_OUTPUT_DIR = Path("output") / "chunker_service" / "chunks"


@app.get("/health")
def health() -> dict[str, str]:
    """Return a basic service health check."""
    return {"status": "ok"}


PreviewPages = Annotated[int | None, Query(gt=0)]


@app.post("/parse")
def parse(file: Annotated[UploadFile, File(...)], preview_pages: PreviewPages = None) -> dict[str, object]:
    """Parse an uploaded PDF and return output file metadata."""
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


MaxTokens = Annotated[int, Query(gt=0)]


@app.post("/chunk")
def chunk(document_id: Annotated[str, Query(min_length=1)], max_tokens: MaxTokens = 512) -> dict[str, object]:
    """Chunk a parser-service Docling JSON output and return chunk metadata."""
    input_path = OUTPUT_DIR / document_id / "docling.json"
    chunker_output = chunk_docling_json_to_output(
        input_path=input_path,
        document_id=document_id,
        output_dir=CHUNK_OUTPUT_DIR / document_id,
        max_tokens=max_tokens,
    )
    return _chunk_response(chunker_output)


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


def _chunk_response(chunker_output: ChunkerOutput) -> dict[str, object]:
    """Build the API response for a chunker output."""
    return {
        "document_id": chunker_output.document_id,
        "input_path": str(chunker_output.input_path),
        "output_dir": str(chunker_output.output_dir),
        "chunker": chunker_output.chunker,
        "max_tokens": chunker_output.max_tokens,
        "chunk_count": chunker_output.chunk_count,
        "files": {
            "chunks": str(chunker_output.chunks_path),
        },
    }
