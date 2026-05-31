"""Load ITB extraction prompt files."""

from __future__ import annotations

from pathlib import Path


def load_prompt(path: str | Path) -> str:
    """Load one UTF-8 prompt file."""
    return Path(path).read_text(encoding="utf-8")
