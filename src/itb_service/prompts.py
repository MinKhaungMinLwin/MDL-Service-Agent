"""Load ITB extraction prompt files."""

from __future__ import annotations

from pathlib import Path

DEFAULT_EXTRACTION_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "itb_keyword_extraction_v2.md"
DEFAULT_VERIFICATION_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "itb_depth_verification.md"
