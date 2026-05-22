"""Azure OpenAI embedding service for standalone test scripts."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from openai import AzureOpenAI

from .config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_EMBEDDING_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    required,
)

logger = logging.getLogger(__name__)


class UnifiedEmbeddingService:
    """Centralized embedding generation service compatible with the POC API."""

    def __init__(
        self,
        model: str = EMBEDDING_MODEL,
        dimensions: int = EMBEDDING_DIMENSIONS,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        api_key: str = AZURE_OPENAI_API_KEY,
        azure_endpoint: str = AZURE_OPENAI_ENDPOINT,
    ) -> None:
        self.model = required(model, "EMBEDDING_MODEL")
        self.dimensions = dimensions
        self.batch_size = batch_size

        parsed = urlparse(required(azure_endpoint, "AZURE_OPENAI_ENDPOINT"))
        azure_base = f"{parsed.scheme}://{parsed.netloc}/"

        self.client = AzureOpenAI(
            api_key=required(api_key, "AZURE_OPENAI_API_KEY"),
            azure_endpoint=azure_base,
            api_version=AZURE_OPENAI_EMBEDDING_API_VERSION,
        )

    @staticmethod
    def build_default() -> "UnifiedEmbeddingService":
        return UnifiedEmbeddingService()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        cleaned_texts = [
            text.strip() if isinstance(text, str) and text.strip() else "N/A"
            for text in texts
        ]

        embeddings: list[list[float]] = []
        for i in range(0, len(cleaned_texts), self.batch_size):
            batch = cleaned_texts[i : i + self.batch_size]
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                    dimensions=self.dimensions,
                )
                embeddings.extend(item.embedding for item in response.data)
            except Exception as exc:
                logger.error("Embedding batch failed: %s", exc)
                embeddings.extend([[0.0] * self.dimensions for _ in batch])

        return embeddings

    def embed_single(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * self.dimensions
        return self.embed_batch([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embed_batch(texts)

    def embed_text(self, text: str) -> list[float]:
        return self.embed_single(text)
