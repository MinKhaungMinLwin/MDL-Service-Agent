"""Semantic embedding index for validation rule matching.

Embeds all rule doc_keyword+item_name texts at build time (cached on disk by
rule-file hash) and exposes cosine-similarity scoring for hybrid rule matching.

Typical usage (called once at server startup):
    index = RuleSemanticIndex.build(rules, cache_dir=Path("data/..."))

Per-query scoring (called after token candidate selection):
    sims = index.score_batch(query_texts)  # list[float], one per rule
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from schedule_service.generate.rule_matching.rule_loader import ValidationRule

_CACHE_FILENAME = "validation_rule_embeddings.json"


@dataclass
class RuleSemanticIndex:
    """Cosine-similarity index over embedded validation rule keywords."""

    embeddings: list[list[float]]   # one embedding per rule, normalized
    rule_texts: list[str]           # what was embedded (for diagnostics)
    _matrix: object = field(default=None, init=False, repr=False, compare=False)  # np.ndarray, lazy

    def _get_matrix(self):
        """Return (n_rules, dims) numpy float32 matrix, built once on first access."""
        if self._matrix is None:
            import numpy as np
            object.__setattr__(self, "_matrix", np.array(self.embeddings, dtype=np.float32))
        return self._matrix

    # ------------------------------------------------------------------ build

    @classmethod
    def build(
        cls,
        rules: list[ValidationRule],
        cache_dir: Path,
        force_rebuild: bool = False,
    ) -> RuleSemanticIndex:
        """Build (or load from cache) the semantic index for *rules*.

        The cache is keyed by a SHA-256 hash of all rule texts so it
        automatically invalidates when the rule CSV changes.
        """
        from common.embedding_client import AzureEmbeddingService

        texts = [_rule_text(r) for r in rules]
        key = _hash_texts(texts)
        cache_path = cache_dir / _CACHE_FILENAME

        if not force_rebuild and cache_path.exists():
            try:
                cached = _load_cache(cache_path)
                if cached.get("key") == key:
                    logger.info("Rule semantic cache HIT ({} rules)", len(rules))
                    embeddings = [_normalize(e) for e in cached["embeddings"]]
                    return cls(embeddings=embeddings, rule_texts=texts)
                logger.info("Rule semantic cache STALE — rebuilding")
            except Exception as exc:
                logger.warning("Rule semantic cache unreadable ({}), rebuilding", exc)

        logger.info("Embedding {} rule texts …", len(texts))
        service = AzureEmbeddingService()
        raw_embeddings = service.embed_texts(texts)
        embeddings = [_normalize(e) for e in raw_embeddings]

        cache_dir.mkdir(parents=True, exist_ok=True)
        _save_cache(cache_path, key, raw_embeddings)
        logger.info("Rule semantic index built and cached → {}", cache_path)
        return cls(embeddings=embeddings, rule_texts=texts)

    # ------------------------------------------------------------------ score

    def score(self, query_embedding: list[float]) -> list[float]:
        """Return cosine similarities between *query_embedding* and all rules."""
        q = _normalize(query_embedding)
        return [_dot(q, e) for e in self.embeddings]

    def score_batch(self, query_embeddings: list[list[float]]) -> list[list[float]]:
        """Return similarity lists for multiple query embeddings."""
        return [self.score(qe) for qe in query_embeddings]

    def score_matrix(self, query_matrix) -> object:
        """Bulk cosine similarity: (n_queries, dims) @ (dims, n_rules) → (n_queries, n_rules).

        query_matrix must be a numpy float32 array with rows already L2-normalised.
        Returns a numpy (n_queries, n_rules) float32 array.
        """
        import numpy as np
        rule_mat = self._get_matrix()  # (n_rules, dims)
        return np.matmul(query_matrix, rule_mat.T)  # (n_queries, n_rules)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rule_text(rule: ValidationRule) -> str:
    """Combine doc_keyword + item_name into one embedding text."""
    parts = [rule.doc_keyword]
    if rule.item_name:
        parts.append(rule.item_name)
    return " ".join(parts)


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if not norm:
        return vector
    return [v / norm for v in vector]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _hash_texts(texts: list[str]) -> str:
    combined = "\n".join(texts).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()[:16]


def _load_cache(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_cache(path: Path, key: str, embeddings: list[list[float]]) -> None:
    path.write_text(
        json.dumps({"key": key, "embeddings": embeddings}, ensure_ascii=False),
        encoding="utf-8",
    )
