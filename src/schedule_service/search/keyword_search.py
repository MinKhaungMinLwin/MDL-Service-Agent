"""Keyword search utilities."""

from __future__ import annotations

import math
import re

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class BM25Index:
    """In-memory BM25 keyword index."""

    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        """Build BM25 statistics for documents."""
        self.k1 = k1
        self.b = b
        self.documents = [tokenize(document) for document in documents]
        self.doc_count = len(self.documents)
        self.avg_doc_len = sum(len(document) for document in self.documents) / max(self.doc_count, 1)
        self.term_freqs: list[dict[str, int]] = []
        doc_freqs: dict[str, int] = {}

        for document in self.documents:
            term_freq: dict[str, int] = {}
            for token in document:
                term_freq[token] = term_freq.get(token, 0) + 1
            self.term_freqs.append(term_freq)
            for token in term_freq:
                doc_freqs[token] = doc_freqs.get(token, 0) + 1

        self.idf = {
            token: math.log(1 + (self.doc_count - freq + 0.5) / (freq + 0.5))
            for token, freq in doc_freqs.items()
        }

    def score(self, query: str) -> list[float]:
        """Score all indexed documents against a query."""
        query_tokens = tokenize(query)
        scores: list[float] = []
        for document, term_freq in zip(self.documents, self.term_freqs, strict=True):
            doc_len = len(document)
            score = 0.0
            for token in query_tokens:
                freq = term_freq.get(token, 0)
                if not freq:
                    continue
                denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / max(self.avg_doc_len, 1))
                score += self.idf.get(token, 0.0) * freq * (self.k1 + 1) / denominator
            scores.append(score)
        return scores


def tokenize(text: str) -> list[str]:
    """Tokenize text for keyword search."""
    return TOKEN_PATTERN.findall(text.lower())
