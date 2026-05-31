"""Load ITB extraction prompt files."""

from __future__ import annotations

from pathlib import Path

DEFAULT_EXTRACTION_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "itb_keyword_extraction_v2.md"
DEFAULT_VERIFICATION_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "itb_depth_verification.md"


def load_prompt(path: str | Path) -> str:
    """Load one UTF-8 prompt file."""
    return Path(path).read_text(encoding="utf-8")
