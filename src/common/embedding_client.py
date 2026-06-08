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
        self.batch_max_chars = env_int("EMBEDDING_BATCH_MAX_CHARS", 60000)
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
        batches = self._embedding_batches(cleaned)
        completed = 0
        for batch_num, batch in enumerate(batches):
            if batch_num > 0 and self.batch_sleep_s > 0:
                time.sleep(self.batch_sleep_s)
            logger.info("Embedding batch {}-{} of {}", completed + 1, completed + len(batch), len(cleaned))
            embeddings.extend(self._embed_batch_with_retry(batch))
            completed += len(batch)
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
                if len(batch) > 1:
                    midpoint = len(batch) // 2
                    logger.warning(
                        "Rate limit hit for {} texts — splitting batch into {} + {}",
                        len(batch),
                        midpoint,
                        len(batch) - midpoint,
                    )
                    return self._embed_batch_with_retry(batch[:midpoint], max_retries) + self._embed_batch_with_retry(
                        batch[midpoint:], max_retries
                    )
                if attempt == max_retries - 1:
                    raise
                wait_s = 65
                logger.warning("Rate limit hit — waiting {}s before retry {}/{}", wait_s, attempt + 1, max_retries - 1)
                time.sleep(wait_s)
        return []  # unreachable

    def _embedding_batches(self, texts: list[str]) -> list[list[str]]:
        """Split texts by item count and total chars to control token-per-minute pressure."""
        batches: list[list[str]] = []
        current: list[str] = []
        current_chars = 0
        max_items = max(self.batch_size, 1)
        max_chars = max(self.batch_max_chars, 1)

        for text in texts:
            text_chars = len(text)
            would_exceed_items = len(current) >= max_items
            would_exceed_chars = current and current_chars + text_chars > max_chars
            if would_exceed_items or would_exceed_chars:
                batches.append(current)
                current = []
                current_chars = 0
            current.append(text)
            current_chars += text_chars

        if current:
            batches.append(current)
        return batches
