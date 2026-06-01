"""Docling HybridChunker wrapper for normalized project chunks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Chunk:
    """Normalized chunk emitted by the chunker service."""

    chunk_id: str
    chunk_index: int
    text: str
    headings: list[str]
    page_start: int | None
    page_end: int | None
    source_refs: list[str]
    token_count: int


def chunk_docling_document(document: Any, document_id: str, max_tokens: int = 512) -> list[Chunk]:
    """Chunk a DoclingDocument using Docling HybridChunker."""
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from transformers import AutoTokenizer

    tokenizer = HuggingFaceTokenizer(
        tokenizer=AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2"),
        max_tokens=max_tokens,
    )
    chunker = HybridChunker(tokenizer=tokenizer, repeat_table_header=True, merge_peers=True)

    chunks: list[Chunk] = []
    for index, docling_chunk in enumerate(chunker.chunk(document), start=1):
        source_refs = _source_refs(docling_chunk)
        pages = _pages(docling_chunk)
        text = docling_chunk.text.strip()
        chunks.append(
            Chunk(
                chunk_id=_chunk_id(document_id, index, text, source_refs),
                chunk_index=index,
                text=text,
                headings=list(docling_chunk.meta.headings or []),
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                source_refs=source_refs,
                token_count=tokenizer.count_tokens(text),
            )
        )

    return chunks


def _source_refs(docling_chunk: Any) -> list[str]:
    """Return Docling source refs used by a chunk."""
    return [item.self_ref for item in docling_chunk.meta.doc_items]


def _pages(docling_chunk: Any) -> list[int]:
    """Return source page numbers used by a chunk."""
    return [
        provenance.page_no
        for item in docling_chunk.meta.doc_items
        for provenance in (item.prov or [])
        if provenance.page_no is not None
    ]


def _chunk_id(document_id: str, chunk_index: int, text: str, source_refs: list[str]) -> str:
    """Build a stable chunk id from document id, source refs, and text."""
    digest = hashlib.sha256(f"{document_id}\n{chunk_index}\n{source_refs}\n{text}".encode()).hexdigest()
    return f"{document_id}_chunk_{chunk_index:06d}_{digest[:12]}"
