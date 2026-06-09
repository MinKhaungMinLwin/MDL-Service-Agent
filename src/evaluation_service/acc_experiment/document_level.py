"""Aggregate ACC chunk-level selections into final ITB document-level MDL lists."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
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

    rows = _build_catalog_rows(predictions)

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


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
