"""ACC-specific adapter for the generic DSPy selector framework."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation_service.acc_experiment.final_selector import load_matching_records
from evaluation_service.selector_tuning.dspy_selector import SelectorExample


def build_acc_selector_examples(
    *,
    matching_dir: Path,
    ground_truth_path: Path,
    top_k: int,
    scope: str = "",
    positive_only: bool = False,
) -> list[SelectorExample]:
    """Build selector supervision examples from ACC matching outputs and ground truth."""
    qrels = _load_positive_qrels(ground_truth_path)
    records = load_matching_records(matching_dir, top_k)
    examples: list[SelectorExample] = []

    for record in records:
        query_id = _query_id(record["itb_scope"], record["chunk_id"])
        if not query_id:
            continue
        if scope and _canonical_scope(record["itb_scope"]) != _canonical_scope(scope):
            continue
        candidate_payload = [
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
            for candidate in record["candidates"]
        ]
        candidate_doc_ids = tuple(candidate["doc_id"] for candidate in record["candidates"])
        truth_ids = qrels.get(query_id, set())
        selected_doc_ids = tuple(doc_id for doc_id in candidate_doc_ids if doc_id in truth_ids)
        if positive_only and not selected_doc_ids:
            continue
        examples.append(
            SelectorExample(
                project_name=record["project_name"],
                itb_scope=record["itb_scope"],
                chunk_id=record["chunk_id"],
                chunk_json=json.dumps(record["itb"], ensure_ascii=False),
                candidate_json=json.dumps(candidate_payload, ensure_ascii=False),
                candidate_doc_ids=candidate_doc_ids,
                selected_doc_ids=selected_doc_ids,
            )
        )
    examples.sort(key=lambda example: (example.itb_scope, example.chunk_id))
    return examples


def _load_positive_qrels(path: Path) -> dict[str, set[str]]:
    qrels: dict[str, set[str]] = defaultdict(set)
    with open(path, newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            query_id = _query_id(row.get("ITB Scope"), row.get("Chunk ID"))
            doc_id = _clean(row.get("MDL Doc ID"))
            if query_id and doc_id:
                qrels[query_id].add(doc_id)
    return dict(qrels)


def _query_id(scope: Any, chunk_id: Any) -> str:
    scope_text = _canonical_scope(_clean(scope))
    chunk_text = _clean(chunk_id)
    return f"{scope_text}||{chunk_text}" if scope_text and chunk_text else ""


def _canonical_scope(scope: str) -> str:
    normalized = "".join(character.casefold() for character in scope if character.isalnum())
    if normalized.startswith("rn"):
        return "R_N_ITB"
    if normalized.startswith("fadhili"):
        return "Fadhili_ITB"
    if normalized.startswith("turkistan"):
        return "Turkistan_ITB"
    return scope


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
