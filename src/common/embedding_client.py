"""Shared embedding client for retrieval services."""

from __future__ import annotations

import time

from loguru import logger
from openai import RateLimitError

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
        self.batch_sleep_s = env_int("EMBEDDING_BATCH_SLEEP_S", 2)
        self.client = build_azure_openai_client(
            api_version_env="AZURE_OPENAI_EMBEDDING_API_VERSION",
            default_api_version="2024-02-01",
        )

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text."""
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in configured batches, with inter-batch sleep and retry on rate-limit errors."""
        embeddings: list[list[float]] = []
        cleaned = [text if text.strip() else "N/A" for text in texts]
        for batch_num, start in enumerate(range(0, len(cleaned), self.batch_size)):
            if batch_num > 0 and self.batch_sleep_s > 0:
                time.sleep(self.batch_sleep_s)
            batch = cleaned[start : start + self.batch_size]
            logger.info("Embedding batch {}-{} of {}", start + 1, start + len(batch), len(cleaned))
            embeddings.extend(self._embed_batch_with_retry(batch))
        return embeddings

    def _embed_batch_with_retry(self, batch: list[str], max_retries: int = 3) -> list[list[float]]:
        """Embed one batch, retrying up to max_retries times on 429 rate-limit errors."""
        for attempt in range(max_retries):
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                    dimensions=self.dimensions,
                )
                return [item.embedding for item in response.data]
            except RateLimitError:
                if attempt == max_retries - 1:
                    raise
                wait_s = 65
                logger.warning(
                    "Rate limit hit — waiting {}s before retry {}/{}", wait_s, attempt + 1, max_retries - 1
                )
                time.sleep(wait_s)
        return []  # unreachable
