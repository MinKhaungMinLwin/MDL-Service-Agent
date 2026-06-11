"""Build ACC experiment ground truth from filtered ITB chunks and MDL catalog."""

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
DEFAULT_ACC_SELECT_PROMPT_PATH = PROMPTS_DIR / "acc_itb_mdl_ground_truth_select.md"
DEFAULT_ACC_VERIFY_PROMPT_PATH = PROMPTS_DIR / "acc_itb_mdl_ground_truth_verify.md"

GROUND_TRUTH_FIELDNAMES = [
    "Project Name",
    "ITB Scope",
    "Document",
    "Chunk ID",
    "Page",
    "Section",
    "Section Path",
    "Hierarchy Context",
    "Keywords",
    "Chunk Text",
    "MDL Doc ID",
    "Source File",
    "Document No",
    "Title",
    "Equipment",
    "Building",
    "System",
    "Study/Survey",
    "Others",
    "Deliverable",
    "Selected MDL Doc IDs",
    "Verified MDL Doc IDs",
    "Rejected MDL Doc IDs",
    "Invalid MDL Doc IDs",
    "No Match",
    "Selector Reason",
    "Verifier Reason",
    "Label Status",
]


@dataclass(frozen=True)
class ACCGroundTruthConfig:
    """Runtime settings for ACC ITB-to-MDL ground truth."""

    model: str
    max_itb_chunks: int = 0
    mdl_batch_size: int = 20
    llm_retries: int = 2
    batch_delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model is required")
        if self.max_itb_chunks < 0:
            raise ValueError("max_itb_chunks cannot be negative")
        if self.mdl_batch_size <= 0:
            raise ValueError("mdl_batch_size must be positive")
        if self.llm_retries < 0:
            raise ValueError("llm_retries cannot be negative")
        if self.batch_delay_seconds < 0:
            raise ValueError("batch_delay_seconds cannot be negative")


class ACCGroundTruthService:
    """Create positive-only ACC ground truth with strict MDL candidate validation."""

    def __init__(
        self,
        config: ACCGroundTruthConfig,
        client: Any,
        select_prompt: str,
        verify_prompt: str,
        sleep=time.sleep,
    ) -> None:
        if not select_prompt:
            raise ValueError("select_prompt is required")
        if not verify_prompt:
            raise ValueError("verify_prompt is required")
        self.config = config
        self.client = client
        self.select_prompt = select_prompt
        self.verify_prompt = verify_prompt
        self.sleep = sleep

    def build(
        self,
        mdl_catalog_path: Path,
        itb_filter_dir: Path,
        output_dir: Path,
        scopes: list[str] | None = None,
    ) -> int:
        """Build ACC ground truth for all selected ITB scopes."""
        mdl_rows = _read_csv(mdl_catalog_path)
        mdl_by_project = _group_mdl_by_project(mdl_rows)
        scope_dirs = _resolve_scope_dirs(itb_filter_dir, scopes)
        if not scope_dirs:
            raise FileNotFoundError(f"No ITB ACC filter scope folders found in {itb_filter_dir}")

        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_dir / "acc_itb_mdl_ground_truth.csv"
        final_rows = _read_csv(final_path)
        completed_keys = {
            (_clean(row.get("ITB Scope")), _clean(row.get("Chunk ID")))
            for row in final_rows
            if _clean(row.get("ITB Scope")) and _clean(row.get("Chunk ID"))
        }

        for scope_dir in scope_dirs:
            itb_scope = scope_dir.name
            itb_rows = _limit_rows(
                _filter_acc_rows(_read_csv(scope_dir / "itb_acc_chunks.csv")),
                self.config.max_itb_chunks,
            )
            project_name = _match_project_name(itb_scope, mdl_by_project.keys())
            candidates = mdl_by_project.get(project_name, [])
            if not candidates:
                logger.warning("No ACC MDL candidates found for ITB scope {} (project {})", itb_scope, project_name)
                continue
            logger.info(
                "Building ACC ground truth for {}: {} ITB chunk(s), {} MDL candidate(s), {} MDL candidate(s)/batch",
                itb_scope,
                len(itb_rows),
                len(candidates),
                self.config.mdl_batch_size,
            )
            candidates_by_id = {_clean(row.get("Doc ID")): row for row in candidates if _clean(row.get("Doc ID"))}
            for index, itb_row in enumerate(itb_rows, start=1):
                chunk_id = _clean(itb_row.get("Chunk ID"))
                if not chunk_id or (itb_scope, chunk_id) in completed_keys:
                    continue
                logger.info("Judging ACC ground truth {}/{}: {} {}", index, len(itb_rows), itb_scope, chunk_id)
                judgment, positives = self._judge_chunk(project_name, itb_scope, itb_row, candidates, candidates_by_id)
                final_rows.extend(
                    _build_ground_truth_rows(project_name, itb_scope, itb_row, judgment, positives, candidates_by_id)
                )
                completed_keys.add((itb_scope, chunk_id))
                _write_csv(final_path, GROUND_TRUTH_FIELDNAMES, _dedupe_final_rows(final_rows))
                self.sleep(self.config.batch_delay_seconds)

        final_rows = _dedupe_final_rows(final_rows)
        _write_csv(final_path, GROUND_TRUTH_FIELDNAMES, final_rows)
        logger.info("Saved {} ACC ground-truth rows: {}", len(final_rows), final_path)
        return len(final_rows)

    def _judge_chunk(
        self,
        project_name: str,
        itb_scope: str,
        itb_row: dict[str, Any],
        candidates: list[dict[str, Any]],
        candidates_by_id: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        selections = []
        candidate_batches = _chunked(candidates, self.config.mdl_batch_size)
        for batch_index, candidate_batch in enumerate(candidate_batches, start=1):
            logger.info(
                "Running ACC ground-truth selector MDL batch {}/{} for {} {} ({} docs)",
                batch_index,
                len(candidate_batches),
                itb_scope,
                _clean(itb_row.get("Chunk ID")),
                len(candidate_batch),
            )
            selection = _run_with_retries(
                lambda batch=candidate_batch: _select_candidates(
                    self.client,
                    self.config.model,
                    self.select_prompt,
                    project_name,
                    itb_scope,
                    itb_row,
                    batch,
                ),
                retries=self.config.llm_retries,
                sleep=self.sleep,
                delay_seconds=self.config.batch_delay_seconds,
                description=(
                    f"select {itb_scope} {_clean(itb_row.get('Chunk ID'))} "
                    f"MDL batch {batch_index}/{len(candidate_batches)}"
                ),
            )
            selections.append(selection)
            self.sleep(self.config.batch_delay_seconds)

        selected_ids = _unique_clean_list(
            doc_id for selection in selections for doc_id in _list_value(selection.get("selected_doc_ids"))
        )
        invalid_ids = [doc_id for doc_id in selected_ids if doc_id not in candidates_by_id]
        valid_ids = [doc_id for doc_id in selected_ids if doc_id in candidates_by_id]
        verifications = []
        if valid_ids:
            logger.info(
                "Running ACC ground-truth verifier for {} {} ({} selected docs)",
                itb_scope,
                _clean(itb_row.get("Chunk ID")),
                len(valid_ids),
            )
            verifications = _run_with_retries(
                lambda: _verify_candidates(
                    self.client,
                    self.config.model,
                    self.verify_prompt,
                    project_name,
                    itb_scope,
                    itb_row,
                    [candidates_by_id[doc_id] for doc_id in valid_ids],
                ),
                retries=self.config.llm_retries,
                sleep=self.sleep,
                delay_seconds=self.config.batch_delay_seconds,
                description=f"verify {itb_scope} {_clean(itb_row.get('Chunk ID'))}",
            )
        verification_by_id = {_clean(row.get("doc_id")): row for row in verifications}
        verified_ids = [
            doc_id
            for doc_id in valid_ids
            if verification_by_id.get(doc_id, {}).get("is_correct_match") is True
        ]
        rejected_ids = [doc_id for doc_id in valid_ids if doc_id not in verified_ids]
        positives = [
            {
                "doc_id": doc_id,
                "selector_reason": _reason_for_doc(selections, doc_id),
                "verifier_reason": _clean(verification_by_id.get(doc_id, {}).get("reason")),
            }
            for doc_id in verified_ids
        ]
        judgment = {
            "Project Name": project_name,
            "ITB Scope": itb_scope,
            "Chunk ID": _clean(itb_row.get("Chunk ID")),
            "Selected MDL Doc IDs": "|".join(valid_ids),
            "Verified MDL Doc IDs": "|".join(verified_ids),
            "Rejected MDL Doc IDs": "|".join(rejected_ids),
            "Invalid MDL Doc IDs": "|".join(invalid_ids),
            "No Match": str(not verified_ids),
            "Selector Reason": _join_selection_reasons(selections),
            "Verifier Reason": _join_verifier_reasons(verification_by_id, verified_ids, rejected_ids),
        }
        return judgment, positives


def _select_candidates(
    client: Any,
    model: str,
    prompt: str,
    project_name: str,
    itb_scope: str,
    itb_row: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "project_name": project_name,
        "itb_scope": itb_scope,
        "itb_chunk": _build_itb_payload(itb_row),
        "mdl_candidates": [_build_mdl_payload(row) for row in candidates],
    }
    result = _run_llm_json(client, model, prompt, payload)
    selected = result.get("selected_doc_ids")
    if not isinstance(selected, list):
        raise ValueError("LLM selection response must contain selected_doc_ids list")
    return result


def _verify_candidates(
    client: Any,
    model: str,
    prompt: str,
    project_name: str,
    itb_scope: str,
    itb_row: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = {
        "project_name": project_name,
        "itb_scope": itb_scope,
        "itb_chunk": _build_itb_payload(itb_row),
        "selected_mdl_candidates": [_build_mdl_payload(row) for row in candidates],
    }
    result = _run_llm_json(client, model, prompt, payload)
    verifications = result.get("verifications")
    if not isinstance(verifications, list):
        raise ValueError("LLM verification response must contain verifications list")
    return [row for row in verifications if isinstance(row, dict)]


def _run_llm_json(client: Any, model: str, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
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
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def _build_ground_truth_rows(
    project_name: str,
    itb_scope: str,
    itb_row: dict[str, Any],
    judgment: dict[str, str],
    positives: list[dict[str, Any]],
    candidates_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    base_row = {
        "Project Name": project_name,
        "ITB Scope": itb_scope,
        "Document": _clean(itb_row.get("Document")),
        "Chunk ID": _clean(itb_row.get("Chunk ID")),
        "Page": _clean(itb_row.get("Page")),
        "Section": _clean(itb_row.get("Section")),
        "Section Path": _clean(itb_row.get("Section Path")),
        "Hierarchy Context": _clean(itb_row.get("Hierarchy Context")),
        "Keywords": _clean(itb_row.get("Keywords")),
        "Chunk Text": _clean(itb_row.get("Chunk Text")),
        "Selected MDL Doc IDs": _clean(judgment.get("Selected MDL Doc IDs")),
        "Verified MDL Doc IDs": _clean(judgment.get("Verified MDL Doc IDs")),
        "Rejected MDL Doc IDs": _clean(judgment.get("Rejected MDL Doc IDs")),
        "Invalid MDL Doc IDs": _clean(judgment.get("Invalid MDL Doc IDs")),
        "No Match": _clean(judgment.get("No Match")),
        "Selector Reason": _clean(judgment.get("Selector Reason")),
        "Verifier Reason": _clean(judgment.get("Verifier Reason")),
    }
    if not positives:
        return [{**base_row, "Label Status": "llm_verified_no_match"}]

    rows = []
    for positive in positives:
        doc_id = positive["doc_id"]
        mdl_row = candidates_by_id[doc_id]
        rows.append(
            {
                **base_row,
                "MDL Doc ID": doc_id,
                "Source File": _clean(mdl_row.get("Source File")),
                "Document No": _clean(mdl_row.get("Document No")),
                "Title": _clean(mdl_row.get("Title")),
                "Equipment": _clean(mdl_row.get("Equipment")),
                "Building": _clean(mdl_row.get("Building")),
                "System": _clean(mdl_row.get("System")),
                "Study/Survey": _clean(mdl_row.get("Study/Survey")),
                "Others": _clean(mdl_row.get("Others")),
                "Deliverable": _clean(mdl_row.get("Deliverable")),
                "Selector Reason": _clean(positive.get("selector_reason")),
                "Verifier Reason": _clean(positive.get("verifier_reason")),
                "Label Status": "llm_verified_positive",
            }
        )
    return rows


def _build_itb_payload(row: dict[str, Any]) -> dict[str, str]:
    return _compact(
        {
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
    )


def _build_mdl_payload(row: dict[str, Any]) -> dict[str, str]:
    return _compact(
        {
            "doc_id": _clean(row.get("Doc ID")),
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
    )


def _resolve_scope_dirs(itb_filter_dir: Path, scopes: list[str] | None) -> list[Path]:
    if scopes:
        return [itb_filter_dir / scope for scope in scopes]
    return sorted(path for path in itb_filter_dir.iterdir() if (path / "itb_acc_chunks.csv").exists())


def _match_project_name(itb_scope: str, project_names: Any) -> str:
    normalized_scope = _normalize_name(itb_scope.removesuffix("_ITB"))
    for project_name in project_names:
        normalized_project = _normalize_name(project_name)
        if normalized_project and normalized_project in normalized_scope:
            return project_name
    aliases = {"rn": "R&N", "rnitb": "R&N"}
    fallback_separator = "&" if itb_scope == "R_N_ITB" else " "
    return aliases.get(normalized_scope, itb_scope.removesuffix("_ITB").replace("_", fallback_separator))


def _group_mdl_by_project(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if "Is ACC Related" in row and not _is_true(row.get("Is ACC Related")):
            continue
        project_name = _clean(row.get("Project Name"))
        doc_id = _clean(row.get("Doc ID"))
        if project_name and doc_id:
            grouped.setdefault(project_name, []).append(row)
    return grouped


def _filter_acc_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _is_true(row.get("Is ACC Related"))]


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


def _limit_rows(rows: list[dict[str, str]], max_rows: int) -> list[dict[str, str]]:
    return rows if max_rows <= 0 else rows[:max_rows]


def _dedupe_final_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_key = {}
    for row in rows:
        scope = _clean(row.get("ITB Scope"))
        chunk_id = _clean(row.get("Chunk ID"))
        doc_id = _clean(row.get("MDL Doc ID")) or "__NO_MATCH__"
        key = (scope, chunk_id, doc_id)
        if scope and chunk_id:
            rows_by_key.setdefault(key, row)
    return [rows_by_key[key] for key in sorted(rows_by_key)]


def _reason_for_doc(selections: list[dict[str, Any]], doc_id: str) -> str:
    for selection in selections:
        selected_ids = {_clean(value) for value in _list_value(selection.get("selected_doc_ids"))}
        if doc_id not in selected_ids:
            continue
        reasons = selection.get("reasons")
        if isinstance(reasons, dict):
            return _clean(reasons.get(doc_id))
        return _clean(selection.get("reason"))
    return ""


def _join_selection_reasons(selections: list[dict[str, Any]]) -> str:
    parts = []
    for index, selection in enumerate(selections, start=1):
        selected_ids = _unique_clean_list(_list_value(selection.get("selected_doc_ids")))
        reason = _clean(selection.get("reason"))
        if selected_ids or reason:
            parts.append(f"batch {index}: selected={','.join(selected_ids) or '-'}; reason={reason}")
    return " | ".join(parts)


def _join_verifier_reasons(
    verification_by_id: dict[str, dict[str, Any]],
    verified_ids: list[str],
    rejected_ids: list[str],
) -> str:
    parts = []
    for doc_id in [*verified_ids, *rejected_ids]:
        reason = _clean(verification_by_id.get(doc_id, {}).get("reason"))
        if reason:
            parts.append(f"{doc_id}: {reason}")
    return " | ".join(parts)


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _unique_clean_list(value: Any) -> list[str]:
    seen = set()
    cleaned = []
    for item in value:
        text = _clean(item)
        if text and text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


def _chunked(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _normalize_name(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _compact(row: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in row.items() if value}


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "yes", "y", "1"}


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
