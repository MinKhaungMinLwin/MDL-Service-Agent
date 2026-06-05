"""Shared models for ITB extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

OUTPUT_HEADER = [
    "Document",
    "Chunk ID",
    "Page",
    "Section",
    "Section Path",
    "Chunk Type",
    "Label",
    "Hierarchy Context",
    "1st Depth",
    "2nd Depth",
    "3rd Depth",
    "4th Depth",
    "5th Depth",
    "Keywords",
    "Search Query",
    "Search Query Source",
    "Confidence",
    "Needs Review",
    "Reason",
    "LLM Verify Valid",
    "LLM Verify Severity",
    "LLM Verify Issues",
    "LLM Suggested Depths",
    "LLM Suggested Keywords",
    "LLM Suggested Search Query",
    "LLM Verify Reason",
    "Chunk Text",
]
TOKEN_HEADER = ["Document", "Page", "Prompt Tokens", "Completion Tokens", "Total Tokens", "Chunk Text"]
REJECTED_HEADER = [
    "Document",
    "Chunk ID",
    "Page",
    "Section",
    "Section Path",
    "Requested Section",
    "Actual Section",
    "Belongs To Requested Section",
    "Boundary Reason",
    "Confidence",
    "Chunk Text",
]


@dataclass(frozen=True)
class ITBTarget:
    """One parsed ITB chunk file and its page range."""

    chunks_file: Path
    document_name: str
    min_page: int | None = None
    max_page: int | None = None

    def __post_init__(self) -> None:
        if self.min_page is None or self.max_page is None:
            return
        if self.min_page > self.max_page:
            raise ValueError("min_page cannot exceed max_page")


@dataclass(frozen=True)
class ITBExtractionConfig:
    """Runtime settings for ITB extraction."""

    model: str
    batch_size: int = 1
    max_concurrency: int = 1
    max_chunks: int = 0
    enable_verification: bool = False
    batch_delay_seconds: float = 1.5
    requested_section: str = ""

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model is required")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if self.max_chunks < 0:
            raise ValueError("max_chunks cannot be negative")
        if self.batch_delay_seconds < 0:
            raise ValueError("batch_delay_seconds cannot be negative")


@dataclass(frozen=True)
class PreparedChunk:
    """One non-empty ITB chunk prepared for LLM extraction."""

    chunk: dict[str, Any]
    hierarchy: str
    known_abbreviations: dict[str, str]
    payload: dict[str, Any]
