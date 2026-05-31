"""Shared runtime configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def load_env_file(path: Path = DEFAULT_ENV_PATH) -> None:
    """Load a simple KEY=VALUE env file without overriding existing variables."""
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def required_env(name: str) -> str:
    """Read a required environment variable."""
    load_env_file()
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a default."""
    load_env_file()
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def azure_endpoint() -> str:
    """Return the normalized Azure OpenAI endpoint root."""
    endpoint = required_env("AZURE_OPENAI_ENDPOINT")
    parsed = urlparse(endpoint)
    return f"{parsed.scheme}://{parsed.netloc}/"
