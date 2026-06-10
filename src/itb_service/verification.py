"""Optional LLM verification for extracted ITB depth metadata."""

from __future__ import annotations

import json
from typing import Any

from common.llm_json import parse_json_output
from itb_service.extraction import parse_batch_results


def verify_extraction_batch(
    client: Any,
    model: str,
    system_prompt: str,
    payloads: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Verify extracted ITB metadata with a second source-grounded LLM pass."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"verifications": payloads}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_completion_tokens=min(8192, 2048 * len(payloads)),
        response_format={"type": "json_object"},
    )
    parsed = parse_json_output(response.choices[0].message.content or "{}")
    return parse_batch_results(parsed, payloads)


def build_verification_payload(
    document_name: str,
    chunk: dict[str, Any],
    hierarchy: str,
    known_abbreviations: dict[str, str],
    extraction: dict[str, Any],
) -> dict[str, Any]:
    """Build one verifier payload from source data and extractor output."""
    return {
        "chunk_id": chunk.get("chunk_id", ""),
        "source_input": {
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
        },
        "extractor_output": extraction,
    }


def failed_verification(error: Exception | str) -> dict[str, Any]:
    """Build an explicit verifier failure result."""
    return {
        "is_valid": False,
        "severity": "error",
        "issues": [str(error)],
        "suggested_depths": {},
        "suggested_keywords": [],
        "reason": "LLM verification failed.",
    }
