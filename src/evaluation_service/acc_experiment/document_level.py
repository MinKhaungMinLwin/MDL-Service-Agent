"""Aggregate ACC chunk-level selections into final ITB project-level MDL lists."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from loguru import logger

from evaluation_service.acc_experiment.llm_judge import (
    build_llm_judge_client,
    judge_model_name,
    judge_project_level_payload,
)

DOCUMENT_LEVEL_FIELDNAMES = [
    "ITB Scope",
    "MDL Doc ID",
    "Document No",
    "Title",
    "Equipment",
    "System",
    "Deliverable",
    "Evidence Chunk IDs",
]

DOCUMENT_LEVEL_SUMMARY_FIELDNAMES = [
    "stage",
    "Project Name",
    "ITB Scope",
    "Ground Truth Count",
    "Predicted Count",
    "Hit Count",
    "Recall",
    "Precision",
    "F1",
]

DOCUMENT_LEVEL_LLM_JUDGE_SUMMARY_FIELDNAMES = [
    "Coverage Score",
    "Purity Score",
    "Readiness Score",
    "Final Score",
    "Confidence",
]

PROJECT_LEVEL_LLM_JUDGE_DETAIL_FIELDNAMES = [
    "Project Name",
    "ITB Scope",
    "Chunk Count",
    "Merged Document Count",
    "Coverage Score",
    "Purity Score",
    "Readiness Score",
    "Final Score",
    "Confidence",
]


def build_document_level_catalog(
    selection_path: Path,
    output_dir: Path,
    scope: str = "",
) -> None:
    """Write one final ITB project-level MDL catalog."""
    predictions = _load_predictions(selection_path)
    if scope:
        canonical_scope = _canonical_scope(scope)
        predictions = {key: value for key, value in predictions.items() if key == canonical_scope}

    catalog_rows = _build_catalog_rows(predictions)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "acc_document_level.csv", DOCUMENT_LEVEL_FIELDNAMES, catalog_rows)


def evaluate_document_level_outputs(
    selection_path: Path,
    ground_truth_path: Path,
    output_dir: Path,
    scope: str = "",
    enable_llm_judge: bool = False,
) -> None:
    """Evaluate ITB project-level outputs and write one summary file plus optional LLM judge details."""
    predictions = _load_predictions(selection_path)
    truth = _load_ground_truth(ground_truth_path)
    if scope:
        canonical_scope = _canonical_scope(scope)
        predictions = {key: value for key, value in predictions.items() if key == canonical_scope}
        truth = {key: value for key, value in truth.items() if key == canonical_scope}

    summary_rows = _evaluate_document_level(predictions, truth)
    for row in summary_rows:
        row["stage"] = "itb_project_level"
    judge_rows: list[dict[str, Any]] = []
    if enable_llm_judge:
        judge_rows, _judge_summary = _evaluate_project_level_judge(predictions, ground_truth_path, scope)
        judge_by_scope = {row["ITB Scope"]: row for row in judge_rows}
        for row in summary_rows:
            judge_row = judge_by_scope.get(_clean(row.get("ITB Scope")), {})
            row.update(
                {
                    "Coverage Score": judge_row.get("Coverage Score", ""),
                    "Purity Score": judge_row.get("Purity Score", ""),
                    "Readiness Score": judge_row.get("Readiness Score", ""),
                    "Final Score": judge_row.get("Final Score", ""),
                    "Confidence": judge_row.get("Confidence", ""),
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_fieldnames = DOCUMENT_LEVEL_SUMMARY_FIELDNAMES.copy()
    if enable_llm_judge:
        summary_fieldnames.extend(DOCUMENT_LEVEL_LLM_JUDGE_SUMMARY_FIELDNAMES)
    _write_csv(output_dir / "summary.csv", summary_fieldnames, summary_rows)
    if enable_llm_judge:
        _write_csv(output_dir / "llm_judge_details.csv", PROJECT_LEVEL_LLM_JUDGE_DETAIL_FIELDNAMES, judge_rows)


def _load_predictions(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    predictions: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in _read_csv(path):
        scope = _canonical_scope(_clean(row.get("ITB Scope")))
        doc_id = _clean(row.get("MDL Doc ID"))
        if not scope or not doc_id:
            continue
        doc = predictions[scope].setdefault(
            doc_id,
            {
                "ITB Scope": scope,
                "MDL Doc ID": doc_id,
                "Document No": _clean(row.get("Document No")),
                "Title": _clean(row.get("Title")),
                "Equipment": _clean(row.get("Equipment")),
                "System": _clean(row.get("System")),
                "Deliverable": _clean(row.get("Deliverable")),
                "_chunk_ids": [],
            },
        )
        _append_unique(doc["_chunk_ids"], _clean(row.get("Chunk ID")))
    return {scope: dict(docs) for scope, docs in predictions.items()}


def _load_ground_truth(path: Path) -> dict[str, set[str]]:
    truth: dict[str, set[str]] = defaultdict(set)
    for row in _read_csv(path):
        scope = _canonical_scope(_clean(row.get("ITB Scope")))
        doc_id = _clean(row.get("MDL Doc ID"))
        if scope and doc_id:
            truth[scope].add(doc_id)
    return dict(truth)


def _build_catalog_rows(predictions: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for docs in predictions.values():
        for doc in docs.values():
            rows.append(
                {key: doc.get(key, "") for key in DOCUMENT_LEVEL_FIELDNAMES if key != "Evidence Chunk IDs"}
                | {"Evidence Chunk IDs": "|".join(doc["_chunk_ids"])}
            )
    return sorted(
        rows,
        key=lambda row: (
            _project_sort_key(row.get("ITB Scope")),
            _clean(row.get("Document No")),
            _clean(row.get("Title")),
            _clean(row.get("MDL Doc ID")),
        ),
    )


def _evaluate_document_level(
    predictions: dict[str, dict[str, dict[str, Any]]],
    truth: dict[str, set[str]],
) -> list[dict[str, Any]]:
    rows = []
    all_scopes = sorted(set(predictions) | set(truth), key=_project_sort_key)
    for scope in all_scopes:
        predicted_docs = predictions.get(scope, {})
        predicted_ids = set(predicted_docs)
        truth_ids = truth.get(scope, set())
        hit_ids = sorted(predicted_ids.intersection(truth_ids))
        missing_ids = sorted(truth_ids - predicted_ids)
        unexpected_ids = sorted(predicted_ids - truth_ids)
        hit_count = len(hit_ids)
        recall = hit_count / len(truth_ids) if truth_ids else None
        precision = hit_count / len(predicted_ids) if predicted_ids else (None if truth_ids else 1.0)
        f1 = _f1(precision, recall)
        rows.append(
            {
                "Project Name": _project_name_from_scope(scope),
                "ITB Scope": scope,
                "Ground Truth Count": len(truth_ids),
                "Predicted Count": len(predicted_ids),
                "Hit Count": hit_count,
                "Recall": "" if recall is None else recall,
                "Precision": "" if precision is None else precision,
                "F1": "" if f1 is None else f1,
                "Ground Truth Doc IDs": "|".join(sorted(truth_ids)),
                "Predicted Doc IDs": "|".join(sorted(predicted_ids)),
                "Missing Ground Truth Doc IDs": "|".join(missing_ids),
                "Unexpected Doc IDs": "|".join(unexpected_ids),
            }
        )
    return rows


def _evaluate_project_level_judge(
    predictions: dict[str, dict[str, dict[str, Any]]],
    ground_truth_path: Path,
    scope: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    model = judge_model_name()
    if not model:
        return [], _empty_judge_summary()
    try:
        client = build_llm_judge_client()
        chunk_summaries = _load_scope_chunks(ground_truth_path)
        rows = []
        all_scopes = sorted(set(predictions) | set(chunk_summaries), key=_project_sort_key)
        for current_scope in all_scopes:
            if scope and current_scope != _canonical_scope(scope):
                continue
            supporting_chunks = chunk_summaries.get(current_scope, [])
            merged_documents = _project_documents(predictions.get(current_scope, {}))
            payload = {
                "project_name": _project_name_from_scope(current_scope),
                "itb_scope": current_scope,
                "supporting_chunks": supporting_chunks,
                "merged_selected_documents": merged_documents,
            }
            scores = judge_project_level_payload(client, model, payload)
            rows.append(
                {
                    "Project Name": _project_name_from_scope(current_scope),
                    "ITB Scope": current_scope,
                    "Chunk Count": len(supporting_chunks),
                    "Merged Document Count": len(merged_documents),
                    "Coverage Score": scores["coverage_score"],
                    "Purity Score": scores["purity_score"],
                    "Readiness Score": scores["readiness_score"],
                    "Final Score": scores["final_score"],
                    "Confidence": scores["confidence"],
                }
            )
        return rows, {
            "avg_llm_coverage_score": _mean_number(row["Coverage Score"] for row in rows),
            "avg_llm_purity_score": _mean_number(row["Purity Score"] for row in rows),
            "avg_llm_readiness_score": _mean_number(row["Readiness Score"] for row in rows),
            "avg_llm_judge_score": _mean_number(row["Final Score"] for row in rows),
        }
    except Exception:
        logger.exception("Project-level LLM judge summary failed")
        return [], _empty_judge_summary()


def _empty_judge_summary() -> dict[str, Any]:
    return {
        "avg_llm_coverage_score": "",
        "avg_llm_purity_score": "",
        "avg_llm_readiness_score": "",
        "avg_llm_judge_score": "",
    }


def _load_scope_chunks(path: Path) -> dict[str, list[dict[str, str]]]:
    chunks: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen = set()
    for row in _read_csv(path):
        scope = _canonical_scope(_clean(row.get("ITB Scope")))
        chunk_id = _clean(row.get("Chunk ID"))
        if not scope or not chunk_id:
            continue
        key = (scope, chunk_id)
        if key in seen:
            continue
        seen.add(key)
        chunks[scope].append(
            {
                "chunk_id": chunk_id,
                "section": _clean(row.get("Section")),
                "hierarchy_context": _clean(row.get("Hierarchy Context")),
                "keywords": _clean(row.get("Keywords")),
                "chunk_text": _clean(row.get("Chunk Text")),
            }
        )
    return {scope: values for scope, values in chunks.items()}


def _project_documents(docs: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for doc in docs.values():
        rows.append(
            {
                "doc_id": _clean(doc.get("MDL Doc ID")),
                "document_no": _clean(doc.get("Document No")),
                "title": _clean(doc.get("Title")),
                "equipment": _clean(doc.get("Equipment")),
                "system": _clean(doc.get("System")),
                "deliverable": _clean(doc.get("Deliverable")),
                "evidence_chunk_ids": "|".join(doc.get("_chunk_ids", [])),
            }
        )
    return sorted(rows, key=lambda row: (_clean(row.get("document_no")), _clean(row.get("doc_id"))))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as file:
        return [dict(row) for row in csv.DictReader(file)]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _mean_number(values: Any) -> float | str:
    numbers = [float(value) for value in values if value != "" and value is not None]
    return mean(numbers) if numbers else ""


def _canonical_scope(scope: str) -> str:
    normalized = "".join(character.casefold() for character in scope if character.isalnum())
    if normalized.startswith("rn"):
        return "R_N_ITB"
    if normalized.startswith("fadhili"):
        return "Fadhili_ITB"
    if normalized.startswith("turkistan"):
        return "Turkistan_ITB"
    return scope


def _project_sort_key(scope: Any) -> tuple[int, str]:
    normalized = _canonical_scope(_clean(scope))
    order = {"Fadhili_ITB": 0, "R_N_ITB": 1, "Turkistan_ITB": 2}
    return order.get(normalized, 99), normalized


def _project_name_from_scope(scope: str) -> str:
    normalized = "".join(character.casefold() for character in scope if character.isalnum())
    if normalized.startswith("rn"):
        return "R&N"
    if normalized.startswith("fadhili"):
        return "Fadhili"
    if normalized.startswith("turkistan"):
        return "Turkistan"
    return scope.removesuffix("_ITB").replace("_", " ")


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
