"""LLM-backed ACC-related MDL document filtering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.llm_json import parse_json_output

DEFAULT_ACC_FILTER_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "acc_mdl_filter.md"


def load_acc_filter_prompt(path: str | Path = DEFAULT_ACC_FILTER_PROMPT_PATH) -> str:
    """Load the ACC MDL filter system prompt."""
    return Path(path).read_text(encoding="utf-8")


def filter_acc_batch(
    client: Any,
    model: str,
    system_prompt: str,
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Classify one batch of MDL catalog rows as ACC-related or not."""
    payload = [_build_payload(row) for row in rows]
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"documents": payload}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_completion_tokens=min(8192, 512 * len(payload)),
        response_format={"type": "json_object"},
    )
    parsed = parse_json_output(response.choices[0].message.content or "{}")
    return parse_acc_filter_results(parsed)


def parse_acc_filter_results(parsed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map ACC filter results by Doc ID."""
    results = parsed.get("results")
    if not isinstance(results, list):
        return {}
    mapped = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        doc_id = _clean(item.get("doc_id"))
        if doc_id:
            mapped[doc_id] = item
    return mapped


def _build_payload(row: dict[str, Any]) -> dict[str, str]:
    return {
        "doc_id": _clean(row.get("Doc ID")),
        "project_name": _clean(row.get("Project Name")),
        "source_file": _clean(row.get("Source File")),
        "document_no": _clean(row.get("Document No")),
        "title": _clean(row.get("Title")),
        "equipment": _clean(row.get("Equipment")),
        "building": _clean(row.get("Building")),
        "system": _clean(row.get("System")),
        "study_survey": _clean(row.get("Study/Survey")),
        "others": _clean(row.get("Others")),
        "deliverable": _clean(row.get("Deliverable")),
        "text_content": _clean(row.get("Text Content")),
    }


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
