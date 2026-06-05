"""Build and write ITB extraction artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from itb_service.extraction import as_list_text, as_text
from itb_service.models import OUTPUT_HEADER, REJECTED_HEADER, TOKEN_HEADER


def build_csv_row(
    document_name: str,
    chunk: dict[str, Any],
    hierarchy: str,
    extraction: dict[str, Any],
    verification: dict[str, Any] | None = None,
) -> list[str]:
    """Convert one extracted source chunk to the downstream CSV schema."""
    depths = [as_text(extraction.get(f"depth_{index}")) for index in range(1, 6)]
    keywords = as_list_text(extraction.get("keywords"))
    return [
        document_name,
        as_text(chunk.get("chunk_id")),
        ", ".join(map(str, chunk.get("page_num", []))),
        as_text(chunk.get("section")),
        as_list_text(chunk.get("section_path")),
        as_text(chunk.get("chunk_type")),
        as_list_text(chunk.get("label")),
        hierarchy,
        *depths,
        keywords,
        _candidate_value(extraction),
        as_text(extraction.get("skip_reason")),
        as_text(extraction.get("confidence")),
        as_text(extraction.get("needs_review")),
        as_text(extraction.get("reason")),
        _source_text(chunk),
    ]


def build_json_record(
    document_name: str,
    chunk: dict[str, Any],
    hierarchy: str,
    extraction: dict[str, Any],
    token_usage: dict[str, int],
    known_abbreviations: dict[str, str],
    verification: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """Build the structured source-of-truth record for one source chunk."""
    record = {
        "document": document_name,
        "chunk_id": chunk.get("chunk_id", ""),
        "pages": chunk.get("page_num", []),
        "section": chunk.get("section", ""),
        "section_path": chunk.get("section_path", ""),
        "chunk_type": chunk.get("chunk_type", ""),
        "label": chunk.get("label", ""),
        "chunk_size_tokens": chunk.get("chunk_size_tokens", ""),
        "extraction_confidence": chunk.get("extraction_confidence", ""),
        "hierarchy_context": hierarchy,
        "known_abbreviations": known_abbreviations,
        "llm_output": extraction,
        "llm_verification": verification or {},
        "token_usage": token_usage,
    }
    if error:
        record["error"] = error
    return record


def build_token_row(
    document_name: str,
    batch_index: int,
    chunks: list[dict[str, Any]],
    token_usage: dict[str, int],
) -> list[Any]:
    """Build one token usage row for a single LLM batch request."""
    chunk_count = len(chunks)
    prompt_tokens = token_usage.get("prompt_tokens", 0)
    completion_tokens = token_usage.get("completion_tokens", 0)
    total_tokens = token_usage.get("total_tokens", 0)
    return [
        document_name,
        batch_index,
        chunk_count,
        ";".join(as_text(chunk.get("chunk_id")) for chunk in chunks if as_text(chunk.get("chunk_id"))),
        _batch_pages(chunks),
        prompt_tokens,
        completion_tokens,
        total_tokens,
        _average_tokens(prompt_tokens, chunk_count),
        _average_tokens(completion_tokens, chunk_count),
        _average_tokens(total_tokens, chunk_count),
    ]


def build_rejected_csv_row(
    document_name: str,
    chunk: dict[str, Any],
    extraction: dict[str, Any],
    requested_section: str,
) -> list[str]:
    """Build one audit row for chunks rejected by the section-boundary check."""
    return [
        document_name,
        as_text(chunk.get("chunk_id")),
        ", ".join(map(str, chunk.get("page_num", []))),
        as_text(chunk.get("section")),
        as_list_text(chunk.get("section_path")),
        requested_section,
        as_text(extraction.get("actual_section")),
        as_text(extraction.get("belongs_to_requested_section")),
        as_text(extraction.get("section_boundary_reason")),
        as_text(extraction.get("confidence")),
        _source_text(chunk),
    ]


def build_rejected_json_record(
    document_name: str,
    chunk: dict[str, Any],
    hierarchy: str,
    extraction: dict[str, Any],
    requested_section: str,
) -> dict[str, Any]:
    """Build one structured audit record for a section-boundary rejection."""
    return {
        "document": document_name,
        "chunk_id": chunk.get("chunk_id", ""),
        "pages": chunk.get("page_num", []),
        "section": chunk.get("section", ""),
        "section_path": chunk.get("section_path", ""),
        "requested_section": requested_section,
        "actual_section": extraction.get("actual_section", ""),
        "belongs_to_requested_section": extraction.get("belongs_to_requested_section", ""),
        "section_boundary_reason": extraction.get("section_boundary_reason", ""),
        "hierarchy_context": hierarchy,
        "llm_output": extraction,
        "chunk_text": _source_text(chunk),
    }


def write_outputs(
    csv_path: str | Path,
    json_path: str | Path,
    token_path: str | Path,
    csv_rows: list[list[Any]],
    json_records: list[dict[str, Any]],
    token_rows: list[list[Any]],
) -> None:
    """Write CSV, JSON, and token usage artifacts."""
    paths = [Path(csv_path), Path(json_path), Path(token_path)]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(paths[0], OUTPUT_HEADER, csv_rows)
    _write_csv(paths[2], TOKEN_HEADER, token_rows)
    paths[1].write_text(json.dumps(json_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv_rows(path: str | Path) -> list[list[str]]:
    """Read existing CSV rows without the header for resume."""
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        next(reader, None)
        return [row for row in reader]


def read_json_records(path: str | Path) -> list[dict[str, Any]]:
    """Read existing structured JSON records for resume."""
    json_path = Path(path)
    if not json_path.exists():
        return []
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected list JSON artifact: {json_path}")
    return data


def write_rejected_outputs(
    csv_path: str | Path,
    json_path: str | Path | None,
    csv_rows: list[list[Any]],
    json_records: list[dict[str, Any]],
) -> None:
    """Write section-boundary rejection audit artifacts."""
    csv_output_path = Path(csv_path)
    csv_output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(csv_output_path, REJECTED_HEADER, csv_rows)
    if json_path is not None:
        json_output_path = Path(json_path)
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        json_output_path.write_text(json.dumps(json_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)


def _source_text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("text") or "")


def _batch_pages(chunks: list[dict[str, Any]]) -> str:
    pages = []
    for chunk in chunks:
        pages.extend(str(page) for page in chunk.get("page_num", []))
    return ", ".join(dict.fromkeys(pages))


def _average_tokens(token_count: int, chunk_count: int) -> float:
    if chunk_count <= 0:
        return 0
    return round(token_count / chunk_count, 2)


def _candidate_value(extraction: dict[str, Any]) -> str:
    value = extraction.get("is_mdl_retrieval_candidate")
    if isinstance(value, bool):
        return str(value)
    if value is None or as_text(value) == "":
        return "True"
    return as_text(value)
