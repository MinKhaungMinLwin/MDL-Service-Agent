"""Chunker service API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

try:
    from chunker_service.service import ChunkerOutput, chunk_docling_json_to_output
except ImportError:
    ChunkerOutput = object
    chunk_docling_json_to_output = None

router = APIRouter(tags=["chunker"])

PARSER_OUTPUT_DIR = Path("output") / "parser_service" / "parsed"
CHUNK_OUTPUT_DIR = Path("output") / "chunker_service" / "chunks"
MaxTokens = Annotated[int, Query(gt=0)]


@router.post("/chunk")
def chunk(document_id: Annotated[str, Query(min_length=1)], max_tokens: MaxTokens = 512) -> dict[str, object]:
    """Chunk a parser-service Docling JSON output and return chunk metadata."""
    if chunk_docling_json_to_output is None:
        raise HTTPException(status_code=503, detail="Chunker service is not available.")

    input_path = PARSER_OUTPUT_DIR / document_id / "docling.json"
    if not input_path.is_file():
        raise HTTPException(status_code=404, detail=f"Parser output not found: {input_path}")

    chunker_output = chunk_docling_json_to_output(
        input_path=input_path,
        document_id=document_id,
        output_dir=CHUNK_OUTPUT_DIR / document_id,
        max_tokens=max_tokens,
    )
    return _response(chunker_output)


def _response(chunker_output: ChunkerOutput) -> dict[str, object]:
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
