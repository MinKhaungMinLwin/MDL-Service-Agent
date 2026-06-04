"""Rank retrieved MDL document candidates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from matching_service.models import Candidate


class BaseReranker(ABC):
    """Rerank retrieved candidates with a query-document relevance model."""

    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        self.model_name = model_name
        self.batch_size = batch_size

    def rerank(self, query_text: str, candidates: list[Candidate], top_k: int) -> list[Candidate]:
        """Score candidates in one batch and return the best matches."""
        if not query_text or not candidates:
            return []

        pairs = [(query_text, build_candidate_text(candidate)) for candidate in candidates]
        scores = self._predict_scores(pairs)
        return _build_reranked_candidates(candidates, scores, top_k)

    @abstractmethod
    def _predict_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Return one relevance score per query-candidate pair."""


class SentenceTransformersCrossEncoderReranker(BaseReranker):
    """Rerank with sentence-transformers CrossEncoder models."""

    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        from sentence_transformers import CrossEncoder

        super().__init__(model_name, batch_size=batch_size)
        self.model = CrossEncoder(model_name)

    def _predict_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        return list(self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False))


class TransformersSequenceClassificationReranker(BaseReranker):
    """Rerank with Hugging Face sequence-classification rerankers."""

    def __init__(self, model_name: str, batch_size: int = 32, trust_remote_code: bool = True) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        super().__init__(model_name, batch_size=batch_size)
        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=trust_remote_code)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_name,
            trust_remote_code=trust_remote_code,
        )
        self.model.eval()
        self.device = getattr(self.model, "device", None)
        if self.tokenizer.pad_token is None and self.tokenizer.eos_token is not None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

    def _predict_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(pairs), self.batch_size):
            batch = pairs[start : start + self.batch_size]
            queries = [query for query, _ in batch]
            candidates = [candidate for _, candidate in batch]
            encoded = self.tokenizer(
                queries,
                candidates,
                padding=True,
                truncation=True,
                return_tensors="pt",
            )
            if self.device is not None:
                encoded = {name: tensor.to(self.device) for name, tensor in encoded.items()}
            with self._torch.no_grad():
                outputs = self.model(**encoded)
            scores.extend(_logits_to_scores(outputs.logits, self.model.config))
        return scores


def create_reranker(model_name: str, batch_size: int = 32, backend: str = "auto") -> BaseReranker:
    """Create the configured reranker backend."""
    resolved_backend = resolve_reranker_backend(model_name, backend)
    if resolved_backend == "sentence_transformers":
        return SentenceTransformersCrossEncoderReranker(model_name, batch_size=batch_size)
    if resolved_backend == "transformers":
        return TransformersSequenceClassificationReranker(model_name, batch_size=batch_size)
    raise ValueError(f"Unsupported reranker backend: {resolved_backend}")


def resolve_reranker_backend(model_name: str, backend: str) -> str:
    """Resolve the reranker backend, preserving the current default behavior."""
    if backend == "auto":
        return "sentence_transformers" if model_name.startswith("cross-encoder/") else "transformers"
    if backend not in {"sentence_transformers", "transformers"}:
        raise ValueError("reranker backend must be auto, sentence_transformers, or transformers")
    return backend


def _build_reranked_candidates(candidates: list[Candidate], scores: list[float], top_k: int) -> list[Candidate]:
    reranked_candidates = []
    for candidate, score in zip(candidates, scores, strict=True):
        reranked_candidate = dict(candidate)
        reranked_candidate["cross_encoder_score"] = float(score)
        reranked_candidates.append(reranked_candidate)

    reranked_candidates.sort(
        key=lambda candidate: (
            candidate["cross_encoder_score"],
            -(candidate.get("retrieval_rank") or len(candidates) + 1),
        ),
        reverse=True,
    )
    for rank, candidate in enumerate(reranked_candidates, start=1):
        candidate["final_rank"] = rank
    return reranked_candidates[:top_k]


def _logits_to_scores(logits: Any, config: Any) -> list[float]:
    if hasattr(logits, "detach"):
        logits = logits.detach()
    if hasattr(logits, "cpu"):
        logits = logits.cpu()
    if hasattr(logits, "tolist"):
        logits = logits.tolist()

    if not logits:
        return []
    if isinstance(logits[0], (int, float)):
        return [float(value) for value in logits]
    if len(logits[0]) == 1:
        return [float(value[0]) for value in logits]

    positive_index = _positive_label_index(config)
    return [float(value[positive_index]) for value in logits]


def _positive_label_index(config: Any) -> int:
    id2label = getattr(config, "id2label", None) or {}
    if id2label:
        normalized = {int(index): str(label).upper() for index, label in id2label.items()}
        for keyword in ("POSITIVE", "RELEVANT", "TRUE", "YES"):
            for index, label in normalized.items():
                if keyword in label:
                    return index
    num_labels = getattr(config, "num_labels", None)
    return 1 if isinstance(num_labels, int) and num_labels > 1 else 0


def build_candidate_text(candidate: dict[str, Any]) -> str:
    """Build a compact MDL representation for relevance scoring."""
    fields = (
        ("Title", "title"),
        ("Equipment", "equipment"),
        ("System", "system"),
        ("Building", "building"),
        ("Study/Survey", "study_survey"),
        ("Others", "others"),
        ("Deliverable", "deliverable"),
        ("Text Content", "text_content"),
    )
    return "\n".join(
        f"{label}: {value}"
        for label, field in fields
        if (value := str(candidate.get(field) or "").strip())
    )


CrossEncoderReranker = SentenceTransformersCrossEncoderReranker
