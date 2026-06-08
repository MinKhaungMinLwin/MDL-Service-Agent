"""Semantic embedding index for validation rule matching."""

from __future__ import annotations

from pathlib import Path

from schedule_service.generate._shared.cosine_index import CosineIndex
from schedule_service.generate.rule.models import ValidationRule


class RuleSemanticIndex(CosineIndex):
    """Cosine-similarity index over embedded validation rule keywords.

    Rows align with the rule list passed to `build`, so a similarity vector returned
    by `score_matrix` can be indexed by `RuleLexicalIndex.rule_position(rule)`.
    """

    _CACHE_FILENAME = "validation_rule_embeddings.json"

    @classmethod
    def build(
        cls,
        rules: list[ValidationRule],
        cache_dir: Path,
        force_rebuild: bool = False,
    ) -> RuleSemanticIndex:
        """Build (or load from disk cache) the semantic index for *rules*."""
        texts = [_rule_text(r) for r in rules]
        return cls._build_from_texts(texts, cache_dir, cls._CACHE_FILENAME, force_rebuild)


def _rule_text(rule: ValidationRule) -> str:
    """Combine doc_keyword + item_name into one embedding text."""
    parts = [rule.doc_keyword]
    if rule.item_name:
        parts.append(rule.item_name)
    return " ".join(parts)
