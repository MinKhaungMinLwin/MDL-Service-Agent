"""Aggregate ACC chunk-level selections into final ITB document-level MDL lists."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

DOCUMENT_LEVEL_FIELDNAMES = [
    "Project Name",
    "ITB Scope",
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
    "Evidence Chunk IDs",
    "Evidence Pages",
    "Evidence Count",
    "Best Rank",
    "Ground Truth MDL Count",
    "Predicted MDL Count",
    "Hit Count",
    "Recall",
    "Precision",
    "F1",
    "Missing Ground Truth Doc IDs",
    "Unexpected Doc IDs",
]


def build_document_level_outputs(
    selection_path: Path,
    ground_truth_path: Path,
    output_dir: Path,
    scope: str = "",
) -> None:
    """Write one final document-level MDL catalog with document-level metrics."""
    predictions = _load_predictions(selection_path)
    truth = _load_ground_truth(ground_truth_path)
    if scope:
        canonical_scope = _canonical_scope(scope)
        predictions = {key: value for key, value in predictions.items() if key == canonical_scope}
        truth = {key: value for key, value in truth.items() if key == canonical_scope}

    catalog_rows = _build_catalog_rows(predictions)
    summary_by_scope = _build_summary_by_scope(predictions, truth)
    rows = _with_summary_columns(catalog_rows, summary_by_scope)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "acc_document_level.csv", DOCUMENT_LEVEL_FIELDNAMES, rows)


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
                "Project Name": _clean(row.get("Project Name")) or _project_name_from_scope(scope),
                "ITB Scope": scope,
                "MDL Doc ID": doc_id,
                "Source File": _clean(row.get("Source File")),
                "Document No": _clean(row.get("Document No")),
                "Title": _clean(row.get("Title")),
                "Equipment": _clean(row.get("Equipment")),
                "Building": _clean(row.get("Building")),
                "System": _clean(row.get("System")),
                "Study/Survey": _clean(row.get("Study/Survey")),
                "Others": _clean(row.get("Others")),
                "Deliverable": _clean(row.get("Deliverable")),
                "_chunk_ids": [],
                "_pages": [],
                "_best_rank": None,
            },
        )
        _append_unique(doc["_chunk_ids"], _clean(row.get("Chunk ID")))
        _append_unique(doc["_pages"], _clean(row.get("Page")))
        rank = _to_int(row.get("Rank"))
        if rank is not None and (doc["_best_rank"] is None or rank < doc["_best_rank"]):
            doc["_best_rank"] = rank
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
                {
                    key: doc.get(key, "")
                    for key in DOCUMENT_LEVEL_FIELDNAMES
                    if key not in {"Evidence Chunk IDs", "Evidence Pages", "Evidence Count", "Best Rank"}
                    and key not in _summary_fieldnames()
                }
                | {
                    "Evidence Chunk IDs": "|".join(doc["_chunk_ids"]),
                    "Evidence Pages": "|".join(doc["_pages"]),
                    "Evidence Count": len(doc["_chunk_ids"]),
                    "Best Rank": "" if doc["_best_rank"] is None else doc["_best_rank"],
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            _project_sort_key(row.get("ITB Scope")),
            _clean(row.get("Source File")),
            _clean(row.get("Document No")),
            _clean(row.get("Title")),
            _clean(row.get("MDL Doc ID")),
        ),
    )


def _build_summary_by_scope(
    predictions: dict[str, dict[str, dict[str, Any]]],
    truth: dict[str, set[str]],
) -> dict[str, dict[str, Any]]:
    rows = {}
    for scope in sorted(set(predictions) | set(truth), key=_project_sort_key):
        predicted_doc_ids = set(predictions.get(scope, {}))
        truth_doc_ids = truth.get(scope, set())
        hit_doc_ids = predicted_doc_ids & truth_doc_ids
        missing = sorted(truth_doc_ids - predicted_doc_ids)
        unexpected = sorted(predicted_doc_ids - truth_doc_ids)
        recall = len(hit_doc_ids) / len(truth_doc_ids) if truth_doc_ids else ""
        precision = len(hit_doc_ids) / len(predicted_doc_ids) if predicted_doc_ids else ("" if truth_doc_ids else 1.0)
        rows[scope] = {
            "Ground Truth MDL Count": len(truth_doc_ids),
            "Predicted MDL Count": len(predicted_doc_ids),
            "Hit Count": len(hit_doc_ids),
            "Recall": recall,
            "Precision": precision,
            "F1": _f1(precision, recall),
            "Missing Ground Truth Doc IDs": "|".join(missing),
            "Unexpected Doc IDs": "|".join(unexpected),
        }
    return rows


def _with_summary_columns(
    catalog_rows: list[dict[str, Any]],
    summary_by_scope: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    scopes_with_catalog = set()
    for row in catalog_rows:
        scope = _canonical_scope(_clean(row.get("ITB Scope")))
        scopes_with_catalog.add(scope)
        rows.append({**row, **summary_by_scope.get(scope, {})})

    for scope, summary in summary_by_scope.items():
        if scope in scopes_with_catalog:
            continue
        rows.append(
            {
                "Project Name": _project_name_from_scope(scope),
                "ITB Scope": scope,
                **summary,
            }
        )
    return rows


def _summary_fieldnames() -> set[str]:
    return {
        "Ground Truth MDL Count",
        "Predicted MDL Count",
        "Hit Count",
        "Recall",
        "Precision",
        "F1",
        "Missing Ground Truth Doc IDs",
        "Unexpected Doc IDs",
    }


def _f1(precision: float | str, recall: float | str) -> float | str:
    if precision == "" or recall == "":
        return ""
    precision_float = float(precision)
    recall_float = float(recall)
    if precision_float + recall_float == 0:
        return 0.0
    return 2 * precision_float * recall_float / (precision_float + recall_float)


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


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _canonical_scope(scope: str) -> str:
    normalized = "".join(character.casefold() for character in scope if character.isalnum())
    if normalized.startswith("rn"):
        return "R_N_ITB"
    if normalized.startswith("fadhili"):
        return "Fadhili_ITB"
    if normalized.startswith("turkistan"):
        return "Turkistan_ITB"
    return scope


def _project_name_from_scope(scope: str) -> str:
    normalized = "".join(character.casefold() for character in scope if character.isalnum())
    if normalized.startswith("rn"):
        return "R&N"
    if normalized.startswith("fadhili"):
        return "Fadhili"
    if normalized.startswith("turkistan"):
        return "Turkistan"
    return scope.removesuffix("_ITB").replace("_", " ")


def _project_sort_key(scope: Any) -> tuple[int, str]:
    normalized = _canonical_scope(_clean(scope))
    order = {"Fadhili_ITB": 0, "R_N_ITB": 1, "Turkistan_ITB": 2}
    return order.get(normalized, 99), normalized


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
