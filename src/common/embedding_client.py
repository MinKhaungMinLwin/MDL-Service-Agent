"""Shared embedding client for retrieval services."""

from __future__ import annotations

from loguru import logger

from common.config import env_int, load_env_file, required_env
from common.openai_client import build_azure_openai_client


class AzureEmbeddingService:
    """Thin Azure OpenAI embedding wrapper."""

    def __init__(self) -> None:
        """Create the embedding client from environment config."""
        load_env_file()
        self.model = required_env("EMBEDDING_MODEL")
        self.dimensions = env_int("EMBEDDING_DIMENSIONS", 1536)
        self.batch_size = env_int("EMBEDDING_BATCH_SIZE", 256)
        self.client = build_azure_openai_client(
            api_version_env="AZURE_OPENAI_EMBEDDING_API_VERSION",
            default_api_version="2024-02-01",
        )

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text."""
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in configured batches."""
        embeddings: list[list[float]] = []
        cleaned = [text if text.strip() else "N/A" for text in texts]
        for start in range(0, len(cleaned), self.batch_size):
            batch = cleaned[start : start + self.batch_size]
            logger.info("Embedding batch {}-{} of {}", start + 1, start + len(batch), len(cleaned))
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self.dimensions,
            )
            embeddings.extend(item.embedding for item in response.data)
        return embeddings
