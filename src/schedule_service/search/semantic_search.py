"""Semantic search utilities."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from urllib.parse import urlparse

from schedule_service.models import ScheduleActivity


class SemanticIndex:
    def __init__(self, embeddings: list[list[float]]) -> None:
        self.embeddings = [_normalize_vector(embedding) for embedding in embeddings]
        self.embedding_service = AzureEmbeddingService()

    @classmethod
    def build(cls, activities: list[ScheduleActivity], cache_dir: Path) -> "SemanticIndex":
        cache_dir.mkdir(parents=True, exist_ok=True)
        service = AzureEmbeddingService()
        target_texts = [activity.target_text for activity in activities]
        cache_path = cache_dir / service.cache_filename("schedule_activities", target_texts)
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return cls(payload["embeddings"])

        embeddings = service.embed_texts(target_texts)
        cache_path.write_text(json.dumps({"embeddings": embeddings}), encoding="utf-8")
        return cls(embeddings)

    def score(self, query: str) -> list[float]:
        query_embedding = _normalize_vector(self.embedding_service.embed_text(query))
        return [_dot(query_embedding, embedding) for embedding in self.embeddings]


class AzureEmbeddingService:
    def __init__(self) -> None:
        _load_env_file(Path("00_current_work/current_test_env/.env"))
        from openai import AzureOpenAI

        endpoint = _required_env("AZURE_OPENAI_ENDPOINT")
        parsed = urlparse(endpoint)
        azure_endpoint = f"{parsed.scheme}://{parsed.netloc}/"
        self.model = _required_env("EMBEDDING_MODEL")
        self.dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
        self.batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "256"))
        self.client = AzureOpenAI(
            api_key=_required_env("AZURE_OPENAI_API_KEY"),
            azure_endpoint=azure_endpoint,
            api_version=os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "2024-02-01"),
        )

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        cleaned = [text if text.strip() else "N/A" for text in texts]
        for start in range(0, len(cleaned), self.batch_size):
            batch = cleaned[start : start + self.batch_size]
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self.dimensions,
            )
            embeddings.extend(item.embedding for item in response.data)
        return embeddings

    def cache_filename(self, prefix: str, texts: list[str]) -> str:
        digest_input = json.dumps(
            {"model": self.model, "dimensions": self.dimensions, "texts": texts},
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]
        return f"{prefix}_{self.model}_{self.dimensions}_{digest}.json"


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
