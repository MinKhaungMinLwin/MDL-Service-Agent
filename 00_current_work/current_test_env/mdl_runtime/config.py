"""Configuration for standalone current_test_env scripts.

Values are loaded from the repository root `.env`, then from the process environment.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is optional at import time.
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env", override=False)


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def required(value: str, label: str) -> str:
    if not value:
        raise ValueError(f"{label} is not configured. Set it in {REPO_ROOT / '.env'} or the process environment.")
    return value


# Azure OpenAI chat/completion settings.
AZURE_OPENAI_ENDPOINT = _env(
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPEN_AI_ENDPOINT",
    default="https://dse-bluedragon-openai.openai.azure.com/",
)
AZURE_OPENAI_API_KEY = _env("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_KEY")
AZURE_OPENAI_CHAT_API_VERSION = _env("AZURE_OPENAI_CHAT_API_VERSION", default="2024-12-01-preview")
AZURE_OPENAI_CHAT_DEPLOYMENT = _env("AZURE_OPENAI_CHAT_DEPLOYMENT", "AZURE_OPEN_AI_DEPLOYMENT", default="gpt-5.2")

# Azure OpenAI embedding settings.
AZURE_OPENAI_EMBEDDING_API_VERSION = _env("AZURE_OPENAI_EMBEDDING_API_VERSION", default="2024-02-01")
EMBEDDING_MODEL = _env("EMBEDDING_MODEL", default="text-embedding-3-large")
EMBEDDING_DIMENSIONS = int(_env("EMBEDDING_DIMENSIONS", default="1536"))
EMBEDDING_BATCH_SIZE = int(_env("EMBEDDING_BATCH_SIZE", default="2048"))

# Neo4j settings.
NEO4J_URI = _env("NEO4J_URI", default="bolt://localhost:7687")
NEO4J_USER = _env("NEO4J_USER", default="neo4j")
NEO4J_PASSWORD = _env("NEO4J_PASSWORD")
NEO4J_DATABASE = _env("NEO4J_DATABASE", default="neo4j")
NEO4J_MAX_POOL_SIZE = int(_env("NEO4J_MAX_POOL_SIZE", default="50"))

