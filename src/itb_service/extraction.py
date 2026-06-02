"""LLM-backed extraction of ITB depth and keyword metadata."""

from __future__ import annotations

import json
import re
from typing import Any

from common.llm_json import parse_json_output


def extract_chunk_batch(
    client: Any,
    model: str,
    system_prompt: str,
    batch_payload: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Extract a batch of source chunks with the chat model."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"chunks": batch_payload}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_completion_tokens=min(8192, 2048 * len(batch_payload)),
        response_format={"type": "json_object"},
    )
    parsed = parse_json_output(response.choices[0].message.content or "{}")
    return parse_batch_results(parsed, batch_payload), get_token_usage(response)


def parse_batch_results(parsed: dict[str, Any], batch_payload: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map model results back to source chunk IDs."""
    if isinstance(parsed.get("results"), list):
        return {
            as_text(item.get("chunk_id")): item
            for item in parsed["results"]
            if isinstance(item, dict) and as_text(item.get("chunk_id"))
        }
    if parsed and len(batch_payload) == 1:
        return {as_text(batch_payload[0].get("chunk_id")): parsed}
    return {}


def get_token_usage(response: Any) -> dict[str, int]:
    """Return normalized token usage from one chat response."""
    usage = response.usage
    return {
        "prompt_tokens": usage.prompt_tokens if usage else 0,
        "completion_tokens": usage.completion_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
    }


def split_token_usage(token_usage: dict[str, int], count: int) -> dict[str, int]:
    """Approximate per-chunk usage for batch calls."""
    if count <= 0:
        return {}
    return {
        "prompt_tokens": round(token_usage.get("prompt_tokens", 0) / count),
        "completion_tokens": round(token_usage.get("completion_tokens", 0) / count),
        "total_tokens": round(token_usage.get("total_tokens", 0) / count),
    }


def fallback_search_query(depths: list[str], keywords: str) -> str:
    """Build a search query when the model omits one."""
    generic_terms = {
        "note",
        "notes",
        "detail",
        "details",
        "general",
        "others",
        "other",
        "miscellaneous",
        "misc",
        "requirement",
        "requirements",
        "data",
        "information",
    }
    meaningful_depths = []
    for depth in depths:
        if not depth or depth.strip().lower() in ("nan", "none"):
            continue
        cleaned_depth = re.sub(r"^[\d\._]+\s*", "", depth.strip()).strip()
        normalized_depth = re.sub(r"[^a-z0-9]+", " ", cleaned_depth.lower()).strip()
        if normalized_depth and normalized_depth not in generic_terms and not normalized_depth.isdigit():
            meaningful_depths.append(cleaned_depth)
    context = " ".join(meaningful_depths[-2:]) if meaningful_depths else ""
    cleaned_keywords = " ".join(
        keyword.strip()
        for keyword in keywords.split(",")
        if keyword.strip() and keyword.strip().lower() not in ("nan", "none")
    )
    return " ".join(value for value in (context, cleaned_keywords) if value).strip()


def failed_extraction(error: Exception | str) -> dict[str, Any]:
    """Build an explicit failed extraction result."""
    message = str(error)
    return {
        "depth_1": "ERROR",
        "depth_2": message,
        "keywords": [],
        "search_query": "",
        "confidence": "low",
        "needs_review": True,
        "reason": message,
    }


def as_text(value: Any) -> str:
    """Convert a scalar value to clean text."""
    return "" if value is None else str(value).strip()


def as_list_text(value: Any) -> str:
    """Convert list-like values to comma-separated text."""
    if isinstance(value, list):
        return ", ".join(as_text(item) for item in value if as_text(item))
    return as_text(value)
