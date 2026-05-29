"""Application service for writing chunker outputs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from loguru import logger

from chunker_service.docling_chunker import Chunk, chunk_docling_document
from chunker_service.docling_loader import load_docling_document


@dataclass(frozen=True)
class ChunkerOutput:
    """File locations and metadata produced by a chunker run."""

    document_id: str
    input_path: Path
    output_dir: Path
    chunks_path: Path
    chunk_count: int
    chunker: str
    max_tokens: int


def chunk_docling_json_to_output(
    input_path: Path,
    document_id: str | None = None,
    output_dir: Path | None = None,
    max_tokens: int = 512,
) -> ChunkerOutput:
    """Chunk a parser-service docling.json file and write chunks.json."""
    resolved_input = input_path.resolve()
    resolved_document_id = document_id or resolved_input.parent.name
    resolved_output = (output_dir or Path("output") / "chunker_service" / "chunks" / resolved_document_id).resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)

    logger.info("Chunking Docling JSON: {}", resolved_input)
    document = load_docling_document(resolved_input)
    chunks = chunk_docling_document(document, resolved_document_id, max_tokens=max_tokens)

    chunks_path = resolved_output / "chunks.json"
    logger.info("Writing chunker output to {}", chunks_path)
    chunks_path.write_text(
        json.dumps(_payload(resolved_document_id, resolved_input, chunks, max_tokens), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return ChunkerOutput(
        document_id=resolved_document_id,
        input_path=resolved_input,
        output_dir=resolved_output,
        chunks_path=chunks_path,
        chunk_count=len(chunks),
        chunker="docling_hybrid",
        max_tokens=max_tokens,
    )


def _payload(document_id: str, input_path: Path, chunks: list[Chunk], max_tokens: int) -> dict[str, object]:
    """Build the JSON payload persisted by the chunker service."""
    return {
        "document_id": document_id,
        "source_path": str(input_path),
        "chunker": "docling_hybrid",
        "max_tokens": max_tokens,
        "chunk_count": len(chunks),
        "chunks": [asdict(chunk) for chunk in chunks],
    }
