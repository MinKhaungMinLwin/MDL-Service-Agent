"""LLM-backed ACC-related ITB chunk filtering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.llm_json import parse_json_output

DEFAULT_ITB_ACC_FILTER_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "acc_itb_filter.md"


def load_itb_acc_filter_prompt(path: str | Path = DEFAULT_ITB_ACC_FILTER_PROMPT_PATH) -> str:
    """Load the ACC ITB chunk filter system prompt."""
    return Path(path).read_text(encoding="utf-8")


def filter_itb_acc_batch(
    client: Any,
    model: str,
    system_prompt: str,
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Classify one batch of ITB extraction rows as ACC-related or not."""
    payload = [_build_payload(row) for row in rows]
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"chunks": payload}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_completion_tokens=min(8192, 512 * len(payload)),
        response_format={"type": "json_object"},
    )
    parsed = parse_json_output(response.choices[0].message.content or "{}")
    return parse_itb_acc_filter_results(parsed)


def parse_itb_acc_filter_results(parsed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map ACC filter results by Chunk ID."""
    results = parsed.get("results")
    if not isinstance(results, list):
        return {}
    mapped = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        chunk_id = _clean(item.get("chunk_id"))
        if chunk_id:
            mapped[chunk_id] = item
    return mapped


def _build_payload(row: dict[str, Any]) -> dict[str, str]:
    return {
        "document": _clean(row.get("Document")),
        "chunk_id": _clean(row.get("Chunk ID")),
        "page": _clean(row.get("Page")),
        "section": _clean(row.get("Section")),
        "section_path": _clean(row.get("Section Path")),
        "hierarchy_context": _clean(row.get("Hierarchy Context")),
        "depth_1": _clean(row.get("1st Depth")),
        "depth_2": _clean(row.get("2nd Depth")),
        "depth_3": _clean(row.get("3rd Depth")),
        "depth_4": _clean(row.get("4th Depth")),
        "depth_5": _clean(row.get("5th Depth")),
        "keywords": _clean(row.get("Keywords")),
        "chunk_text": _clean(row.get("Chunk Text")),
    }


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
