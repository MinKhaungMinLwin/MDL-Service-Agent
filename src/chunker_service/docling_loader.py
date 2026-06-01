"""Load Docling JSON outputs from parser service."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_docling_document(json_path: Path) -> Any:
    """Load a DoclingDocument from a parser-service docling.json file."""
    from docling_core.types.doc import DoclingDocument

    return DoclingDocument.load_from_json(json_path)
