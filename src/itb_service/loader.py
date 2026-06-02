"""Load and normalize parsed ITB chunks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from itb_service.models import ITBTarget, PreparedChunk


def load_abbreviation_rules(path: str | Path) -> dict[str, str]:
    """Load abbreviation variants mapped to canonical names."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = {}
    for canonical, variants in payload.items():
        rules[canonical] = canonical
        for variant in variants:
            rules[variant] = canonical
    return rules


def load_target_chunks(target: ITBTarget, max_chunks: int = 0) -> list[dict[str, Any]]:
    """Load ITB chunks whose pages overlap the configured target range."""
    data = json.loads(target.chunks_file.read_text(encoding="utf-8"))
    chunks = [
        chunk
        for chunk in data.get("chunks", [])
        if any(target.min_page <= page <= target.max_page for page in chunk.get("page_num", []))
    ]
    return chunks[:max_chunks] if max_chunks > 0 else chunks


def prepare_chunks(
    document_name: str,
    chunks: list[dict[str, Any]],
    abbreviation_rules: dict[str, str],
    requested_section: str = "",
) -> list[PreparedChunk]:
    """Normalize and prepare non-empty source chunks for extraction."""
    prepared = []
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        if not text.strip():
            continue
        hierarchy = normalize_hierarchy(str(chunk.get("hierarchy_context", "")), document_name)
        known_abbreviations = find_known_abbreviations(f"{hierarchy}\n{text}", abbreviation_rules)
        prepared.append(
            PreparedChunk(
                chunk=chunk,
                hierarchy=hierarchy,
                known_abbreviations=known_abbreviations,
                payload=build_chunk_payload(document_name, chunk, hierarchy, known_abbreviations, requested_section),
            )
        )
    return prepared


def find_known_abbreviations(text: str, rules: dict[str, str]) -> dict[str, str]:
    """Return abbreviation rules relevant to a chunk."""
    found = {}
    for variant, canonical in sorted(rules.items(), key=lambda item: len(item[0]), reverse=True):
        if variant.casefold() == canonical.casefold():
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(variant)}(?![A-Za-z0-9])", re.IGNORECASE)
        if pattern.search(text):
            found[variant] = canonical
    return found


def normalize_hierarchy(hierarchy: str, document_name: str) -> str:
    """Remove local wrapper path parts from a chunk hierarchy."""
    parts = [part.strip() for part in hierarchy.split(" > ") if part.strip()]
    filtered_parts = [part for part in parts if part not in ("test_temp", document_name)]
    return " > ".join(filtered_parts).replace(",", " ")


def build_chunk_payload(
    document_name: str,
    chunk: dict[str, Any],
    hierarchy: str,
    known_abbreviations: dict[str, str],
    requested_section: str = "",
) -> dict[str, Any]:
    """Build one source-grounded chunk payload for model extraction."""
    payload = {
        "document": document_name,
        "chunk_id": chunk.get("chunk_id", ""),
        "pages": chunk.get("page_num", []),
        "section": chunk.get("section", ""),
        "section_path": chunk.get("section_path", ""),
        "chunk_type": chunk.get("chunk_type", ""),
        "label": chunk.get("label", ""),
        "hierarchy_context": hierarchy,
        "known_abbreviations": known_abbreviations,
        "chunk_text": chunk.get("text", ""),
    }
    if requested_section:
        payload["requested_section"] = requested_section
    return payload
