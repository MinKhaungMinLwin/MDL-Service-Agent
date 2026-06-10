"""Aggregate ACC chunk-level selections into final ITB project-level MDL lists."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

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
    "scopes",
    "positive_scopes",
    "avg_precision",
    "avg_f1",
    "avg_recall",
]


def build_document_level_outputs(
    selection_path: Path,
    ground_truth_path: Path,
    output_dir: Path,
    scope: str = "",
    write_catalog: bool = True,
    write_summary: bool = True,
) -> None:
    """Write one final ITB project-level MDL catalog with project-level metrics."""
    predictions = _load_predictions(selection_path)
    truth = _load_ground_truth(ground_truth_path)
    if scope:
        canonical_scope = _canonical_scope(scope)
        predictions = {key: value for key, value in predictions.items() if key == canonical_scope}
        truth = {key: value for key, value in truth.items() if key == canonical_scope}

    catalog_rows = _build_catalog_rows(predictions)
    eval_rows = _evaluate_document_level(predictions, truth)
    summary_rows = [{"stage": "itb_project_level", **_summarize_document_level(eval_rows)}]

    output_dir.mkdir(parents=True, exist_ok=True)
    if write_catalog:
        _write_csv(output_dir / "acc_document_level.csv", DOCUMENT_LEVEL_FIELDNAMES, catalog_rows)
    if write_summary:
        _write_csv(output_dir / "summary.csv", DOCUMENT_LEVEL_SUMMARY_FIELDNAMES, summary_rows)


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


def _summarize_document_level(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [row for row in rows if int(row["Ground Truth Count"]) > 0]
    return {
        "scopes": len(rows),
        "positive_scopes": len(positive_rows),
        "avg_recall": _mean_number(row["Recall"] for row in positive_rows),
        "avg_precision": _mean_number(row["Precision"] for row in positive_rows),
        "avg_f1": _mean_number(row["F1"] for row in positive_rows),
    }


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
