"""LLM final selector for ACC experiment matching candidates."""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from common.llm_json import parse_json_output

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_FINAL_SELECTOR_PROMPT_PATH = PROMPTS_DIR / "acc_final_selector.md"

SELECTION_FIELDNAMES = [
    "Project Name",
    "ITB Scope",
    "Document",
    "Chunk ID",
    "Page",
    "MDL Doc ID",
    "Rank",
    "Source File",
    "Document No",
    "Title",
    "Equipment",
    "Building",
    "System",
    "Study/Survey",
    "Others",
    "Deliverable",
    "Selector Reason",
]

JUDGMENT_FIELDNAMES = [
    "Project Name",
    "ITB Scope",
    "Document",
    "Chunk ID",
    "Candidate Count",
    "Top K Doc IDs",
    "Selected MDL Doc IDs",
    "Invalid MDL Doc IDs",
    "No Match",
    "Reason",
]


@dataclass(frozen=True)
class ACCFinalSelectorConfig:
    """Runtime settings for ACC LLM final selection."""

    model: str
    top_k: int = 20
    llm_retries: int = 2
    batch_delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model is required")
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.llm_retries < 0:
            raise ValueError("llm_retries cannot be negative")
        if self.batch_delay_seconds < 0:
            raise ValueError("batch_delay_seconds cannot be negative")


class ACCFinalSelectorService:
    """Select final MDL matches from cross-encoder Top-K candidates."""

    def __init__(
        self,
        config: ACCFinalSelectorConfig,
        client: Any,
        prompt: str,
        sleep=time.sleep,
    ) -> None:
        if not prompt:
            raise ValueError("prompt is required")
        self.config = config
        self.client = client
        self.prompt = prompt
        self.sleep = sleep

    def select(self, matching_dir: Path, output_dir: Path) -> int:
        """Run final LLM selection for all matching CSV files under a matching directory."""
        records = load_matching_records(matching_dir, self.config.top_k)
        if not records:
            raise FileNotFoundError(f"No matching CSV records found in {matching_dir}")

        output_dir.mkdir(parents=True, exist_ok=True)
        judgment_path = output_dir / "acc_llm_final_selection_judgments.csv"
        selection_path = output_dir / "acc_llm_final_selection.csv"
        judgment_rows = _read_csv(judgment_path)
        selection_rows = _read_csv(selection_path)
        completed = {
            (_clean(row.get("ITB Scope")), _clean(row.get("Chunk ID")))
            for row in judgment_rows
            if _clean(row.get("ITB Scope")) and _clean(row.get("Chunk ID"))
        }

        for index, record in enumerate(records, start=1):
            key = (record["itb_scope"], record["chunk_id"])
            if key in completed:
                continue
            logger.info(
                "Running ACC final selector {}/{}: {} {} ({} candidate{})",
                index,
                len(records),
                record["itb_scope"],
                record["chunk_id"],
                len(record["candidates"]),
                "" if len(record["candidates"]) == 1 else "s",
            )
            result = _run_with_retries(
                lambda current_record=record: _select_record(
                    self.client,
                    self.config.model,
                    self.prompt,
                    current_record,
                ),
                retries=self.config.llm_retries,
                sleep=self.sleep,
                delay_seconds=self.config.batch_delay_seconds,
                description=f"final select {record['itb_scope']} {record['chunk_id']}",
            )
            judgment, selections = _resolve_selection(record, result)
            judgment_rows.append(judgment)
            selection_rows.extend(selections)
            completed.add(key)
            _write_csv(judgment_path, JUDGMENT_FIELDNAMES, judgment_rows)
            _write_csv(selection_path, SELECTION_FIELDNAMES, _dedupe_selection_rows(selection_rows))
            self.sleep(self.config.batch_delay_seconds)

        selection_rows = _dedupe_selection_rows(selection_rows)
        _write_csv(judgment_path, JUDGMENT_FIELDNAMES, judgment_rows)
        _write_csv(selection_path, SELECTION_FIELDNAMES, selection_rows)
        logger.info("Saved {} ACC final selected rows: {}", len(selection_rows), selection_path)
        return len(selection_rows)


def load_matching_records(matching_dir: Path, top_k: int) -> list[dict[str, Any]]:
    """Load matching CSV rows with cross-encoder candidate details."""
    records = []
    for path in sorted(matching_dir.rglob("*.csv")):
        if not path.name.startswith("output_match_"):
            continue
        for row in _read_csv(path):
            candidates = _candidate_rows(row, top_k)
            if not candidates:
                continue
            itb_scope = _clean(row.get("Document")) or _infer_scope_from_path(path)
            records.append(
                {
                    "project_name": _project_name_from_scope(itb_scope),
                    "itb_scope": itb_scope,
                    "document": _clean(row.get("Document")),
                    "chunk_id": _clean(row.get("Chunk ID")),
                    "page": _clean(row.get("Page")),
                    "itb": _build_itb_payload(row),
                    "candidates": candidates,
                    "retrieval_doc_ids": _split_doc_ids(row.get("Retrieval_Doc_IDs")),
                    "source_path": str(path),
                }
            )
    records.sort(key=lambda record: (record["itb_scope"], record["chunk_id"]))
    return records


def _select_record(client: Any, model: str, prompt: str, record: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "project_name": record["project_name"],
        "itb_scope": record["itb_scope"],
        "itb_chunk": record["itb"],
        "top_k_mdl_candidates": [_build_candidate_payload(candidate) for candidate in record["candidates"]],
    }
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_completion_tokens=4096,
        response_format={"type": "json_object"},
    )
    parsed = parse_json_output(response.choices[0].message.content or "{}")
    if not isinstance(parsed.get("selected_doc_ids"), list):
        raise ValueError("LLM response must contain selected_doc_ids list")
    return parsed


def _resolve_selection(record: dict[str, Any], result: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, str]]]:
    candidates_by_id = {candidate["doc_id"]: candidate for candidate in record["candidates"]}
    selected_ids = _unique_clean_list(result.get("selected_doc_ids"))
    valid_ids = [doc_id for doc_id in selected_ids if doc_id in candidates_by_id]
    invalid_ids = [doc_id for doc_id in selected_ids if doc_id not in candidates_by_id]
    reasons = result.get("reasons") if isinstance(result.get("reasons"), dict) else {}
    judgment = {
        "Project Name": record["project_name"],
        "ITB Scope": record["itb_scope"],
        "Document": record["document"],
        "Chunk ID": record["chunk_id"],
        "Candidate Count": len(record["candidates"]),
        "Top K Doc IDs": "|".join(candidate["doc_id"] for candidate in record["candidates"]),
        "Selected MDL Doc IDs": "|".join(valid_ids),
        "Invalid MDL Doc IDs": "|".join(invalid_ids),
        "No Match": str(not valid_ids),
        "Reason": _clean(result.get("reason")),
    }
    selections = []
    for doc_id in valid_ids:
        candidate = candidates_by_id[doc_id]
        selections.append(
            {
                "Project Name": record["project_name"],
                "ITB Scope": record["itb_scope"],
                "Document": record["document"],
                "Chunk ID": record["chunk_id"],
                "Page": record["page"],
                "MDL Doc ID": doc_id,
                "Rank": candidate["rank"],
                "Source File": candidate["source_file"],
                "Document No": candidate["document_no"],
                "Title": candidate["title"],
                "Equipment": candidate["equipment"],
                "Building": candidate["building"],
                "System": candidate["system"],
                "Study/Survey": candidate["study_survey"],
                "Others": candidate["others"],
                "Deliverable": candidate["deliverable"],
                "Selector Reason": _clean(reasons.get(doc_id)) or _clean(result.get("reason")),
            }
        )
    return judgment, selections


def _candidate_rows(row: dict[str, Any], top_k: int) -> list[dict[str, str]]:
    candidates = []
    for index in range(1, top_k + 1):
        prefix = f"Matched_Doc_{index}"
        doc_id = _clean(row.get(f"{prefix}_Doc_ID"))
        if not doc_id:
            continue
        candidates.append(
            {
                "rank": str(index),
                "doc_id": doc_id,
                "source_file": _clean(row.get(f"{prefix}_Source_File")),
                "document_no": _clean(row.get(f"{prefix}_Document_No")),
                "title": _clean(row.get(f"{prefix}_Title")),
                "equipment": _clean(row.get(f"{prefix}_Equipment")),
                "building": _clean(row.get(f"{prefix}_Building")),
                "system": _clean(row.get(f"{prefix}_System")),
                "study_survey": _clean(row.get(f"{prefix}_Study_Survey")),
                "others": _clean(row.get(f"{prefix}_Others")),
                "deliverable": _clean(row.get(f"{prefix}_Deliverable")),
                "text_content": _clean(row.get(f"{prefix}_Text_Content")),
            }
        )
    return candidates


def _build_itb_payload(row: dict[str, Any]) -> dict[str, str]:
    return _compact(
        {
            "document": _clean(row.get("Document")),
            "chunk_id": _clean(row.get("Chunk ID")),
            "page": _clean(row.get("Page")),
            "depth_1": _clean(row.get("1st Depth")),
            "depth_2": _clean(row.get("2nd Depth")),
            "depth_3": _clean(row.get("3rd Depth")),
            "depth_4": _clean(row.get("4th Depth")),
            "depth_5": _clean(row.get("5th Depth")),
            "depth_context": _clean(row.get("Depth_Context")),
            "keywords": _clean(row.get("Keywords")),
            "chunk_text": _clean(row.get("Chunk Text")),
        }
    )


def _build_candidate_payload(candidate: dict[str, str]) -> dict[str, str]:
    return _compact(
        {
            "rank": candidate["rank"],
            "doc_id": candidate["doc_id"],
            "document_no": candidate["document_no"],
            "title": candidate["title"],
            "equipment": candidate["equipment"],
            "building": candidate["building"],
            "system": candidate["system"],
            "study_survey": candidate["study_survey"],
            "others": candidate["others"],
            "deliverable": candidate["deliverable"],
            "text_content": candidate["text_content"],
        }
    )


def _infer_scope_from_path(path: Path) -> str:
    for part in reversed(path.parts):
        if part.endswith("_ITB"):
            return part
    return path.stem


def _project_name_from_scope(scope: str) -> str:
    normalized = "".join(character.casefold() for character in scope if character.isalnum())
    if normalized.startswith("rn"):
        return "R&N"
    if normalized.startswith("fadhili"):
        return "Fadhili"
    if normalized.startswith("turkistan"):
        return "Turkistan"
    return scope.removesuffix("_ITB").replace("_", " ")


def _run_with_retries(operation, retries: int, sleep, delay_seconds: float, description: str):
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt > retries:
                break
            logger.warning("{} failed on attempt {}/{}: {}", description, attempt, retries + 1, exc)
            sleep(delay_seconds * attempt)
    if last_error is not None:
        raise last_error
    raise AssertionError("unreachable")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as file:
        return [dict(row) for row in csv.DictReader(file)]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _dedupe_selection_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_key = {}
    for row in rows:
        key = (_clean(row.get("ITB Scope")), _clean(row.get("Chunk ID")), _clean(row.get("MDL Doc ID")))
        if all(key):
            rows_by_key.setdefault(key, row)
    return [rows_by_key[key] for key in sorted(rows_by_key)]


def _unique_clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen = set()
    cleaned = []
    for item in value:
        text = _clean(item)
        if text and text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


def _split_doc_ids(value: Any) -> list[str]:
    seen = set()
    doc_ids = []
    for doc_id in str(value or "").split("|"):
        doc_id = doc_id.strip()
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            doc_ids.append(doc_id)
    return doc_ids


def _compact(row: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in row.items() if value}


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
