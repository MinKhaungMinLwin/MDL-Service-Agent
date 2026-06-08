"""Evaluate ACC experiment retrieval, cross-encoder, and LLM final selection."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from evaluation_service.acc_experiment.final_selector import load_matching_records
from evaluation_service.matching_evaluation.metrics import evaluate_cross_encoder, evaluate_retrieval

SUMMARY_BASE_FIELDNAMES = [
    "stage",
    "queries",
    "positive_queries",
    "avg_precision",
    "avg_f1",
]

Qrels = dict[str, dict[str, int]]
Rankings = dict[str, list[str]]


def evaluate_acc_experiment(
    ground_truth_path: Path,
    matching_dir: Path,
    output_dir: Path,
    llm_selection_path: Path | None = None,
    retrieval_k: int = 100,
    cross_encoder_k: int = 20,
    llm_k: int = 0,
    scope: str = "",
) -> None:
    """Evaluate ACC artifacts using the shared retrieval/cross-encoder metrics."""
    qrels = _load_positive_qrels(ground_truth_path)
    query_info = _load_query_info(ground_truth_path, qrels)
    matching_rankings = _load_matching_rankings(matching_dir, cross_encoder_k)
    if scope:
        qrels = _filter_by_scope(qrels, scope)
        query_info = _filter_by_scope(query_info, scope)
        matching_rankings = {
            stage: _filter_by_scope(rankings, scope)
            for stage, rankings in matching_rankings.items()
        }

    summary_rows: list[dict[str, Any]] = []

    retrieval_stage = f"retrieval@{retrieval_k}"
    retrieval_rankings = _clip_rankings(matching_rankings["retrieval"], retrieval_k)
    retrieval_summary, _retrieval_metrics = evaluate_retrieval(qrels, retrieval_rankings, k=retrieval_k)
    summary_rows.append(
        {
            "stage": retrieval_stage,
            **_drop_hit_rate_metrics(retrieval_summary),
        }
    )

    cross_encoder_stage = f"cross_encoder@{cross_encoder_k}"
    cross_encoder_rankings = _clip_rankings(matching_rankings["cross_encoder"], cross_encoder_k)
    cross_encoder_summary, _cross_encoder_metrics = evaluate_cross_encoder(
        qrels,
        cross_encoder_rankings,
        k=cross_encoder_k,
    )
    summary_rows.append(
        {
            "stage": cross_encoder_stage,
            **_drop_hit_rate_metrics(cross_encoder_summary),
        }
    )

    if llm_selection_path:
        llm_stage = f"llm_final@{llm_k}" if llm_k > 0 else "llm_final"
        llm_rankings = _clip_rankings(_load_llm_rankings(llm_selection_path), llm_k)
        if scope:
            llm_rankings = _filter_by_scope(llm_rankings, scope)
        llm_rows = [
            _evaluate_selected_set(query_id, qrels.get(query_id, {}), llm_rankings.get(query_id, []), query_info)
            for query_id in sorted(set(query_info) | set(qrels) | set(llm_rankings))
        ]
        summary_rows.append({"stage": llm_stage, **_summarize_selected_set(llm_rows)})

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "summary.csv", _fieldnames(SUMMARY_BASE_FIELDNAMES, summary_rows), summary_rows)


def _load_positive_qrels(path: Path) -> Qrels:
    qrels: Qrels = defaultdict(dict)
    for row in _read_csv(path):
        query_id = _query_id(row.get("ITB Scope"), row.get("Chunk ID"))
        doc_id = _clean(row.get("MDL Doc ID"))
        if query_id and doc_id:
            qrels[query_id][doc_id] = 3
    return dict(qrels)


def _load_query_info(judgment_path: Path, qrels: Qrels) -> dict[str, dict[str, str]]:
    info = {}
    for row in _read_csv(judgment_path):
        query_id = _query_id(row.get("ITB Scope"), row.get("Chunk ID"))
        if query_id:
            info[query_id] = {
                "Project Name": _clean(row.get("Project Name")),
                "ITB Scope": _clean(row.get("ITB Scope")),
                "Chunk ID": _clean(row.get("Chunk ID")),
                "No Match Query": str(_clean(row.get("No Match")).casefold() == "true"),
            }
    for query_id in qrels:
        scope, chunk_id = _split_query_id(query_id)
        info.setdefault(
            query_id,
            {
                "Project Name": _project_name_from_scope(scope),
                "ITB Scope": scope,
                "Chunk ID": chunk_id,
                "No Match Query": "False",
            },
        )
    return info


def _load_matching_rankings(matching_dir: Path, cross_encoder_k: int) -> dict[str, Rankings]:
    records = load_matching_records(matching_dir, cross_encoder_k)
    retrieval: Rankings = {}
    cross_encoder: Rankings = {}
    for record in records:
        query_id = _query_id(record["itb_scope"], record["chunk_id"])
        if not query_id:
            continue
        retrieval[query_id] = record.get("retrieval_doc_ids", [])
        cross_encoder[query_id] = [candidate["doc_id"] for candidate in record["candidates"]]
    return {"retrieval": retrieval, "cross_encoder": cross_encoder}


def _load_llm_rankings(path: Path) -> Rankings:
    rankings: Rankings = {}
    if not path.exists():
        return rankings
    for row in _read_csv(path):
        query_id = _query_id(row.get("ITB Scope"), row.get("Chunk ID"))
        if not query_id:
            continue
        if "Selected MDL Doc IDs" in row:
            rankings.setdefault(query_id, [])
            rankings[query_id] = _merge_doc_ids(
                rankings[query_id],
                _split_doc_ids(row.get("Selected MDL Doc IDs")),
            )
        elif doc_id := _clean(row.get("MDL Doc ID")):
            rankings.setdefault(query_id, []).append(doc_id)
    return rankings


def _evaluate_selected_set(
    query_id: str,
    truth: dict[str, int],
    predicted: list[str],
    query_info: dict[str, dict[str, str]],
) -> dict[str, Any]:
    truth_set = set(truth)
    predicted_set = set(predicted)
    hit_count = len(truth_set.intersection(predicted_set))
    recall = hit_count / len(truth_set) if truth_set else None
    precision = hit_count / len(predicted_set) if predicted_set else (None if truth_set else 1.0)
    f1 = _f1(precision, recall)
    unexpected = sorted(predicted_set - truth_set)
    missing = sorted(truth_set - predicted_set)
    scope, chunk_id = _split_query_id(query_id)
    info = query_info.get(query_id, {})
    no_match_query = not truth_set
    return {
        "Project Name": info.get("Project Name") or _project_name_from_scope(scope),
        "ITB Scope": scope,
        "Chunk ID": chunk_id,
        "Ground Truth Count": len(truth_set),
        "Predicted Count": len(predicted_set),
        "Hit Count": hit_count,
        "Precision": "" if precision is None else precision,
        "F1": "" if f1 is None else f1,
        "No Match Query": str(no_match_query),
        "Ground Truth Doc IDs": "|".join(sorted(truth_set)),
        "Predicted Doc IDs": "|".join(predicted),
        "Missing Ground Truth Doc IDs": "|".join(missing),
        "Unexpected Doc IDs": "|".join(unexpected),
    }


def _summarize_selected_set(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [row for row in rows if int(row["Ground Truth Count"]) > 0]
    return {
        "queries": len(rows),
        "positive_queries": len(positive_rows),
        "avg_recall": _mean_number(_selected_recall(row) for row in positive_rows),
        "avg_precision": _mean_number(row["Precision"] for row in positive_rows),
        "avg_f1": _mean_number(row["F1"] for row in positive_rows),
    }


def _drop_hit_rate_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("hit_rate")}


def _filter_by_scope(rows: dict[str, Any], scope: str) -> dict[str, Any]:
    canonical_scope = _canonical_scope(scope)
    return {
        query_id: value
        for query_id, value in rows.items()
        if _split_query_id(query_id)[0] == canonical_scope
    }


def _selected_recall(row: dict[str, Any]) -> float | str:
    truth_count = int(row["Ground Truth Count"])
    return int(row["Hit Count"]) / truth_count if truth_count else ""


def _clip_rankings(rankings: Rankings, limit: int) -> Rankings:
    if limit <= 0:
        return rankings
    return {key: value[:limit] for key, value in rankings.items()}


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _mean_number(values: Any) -> float | str:
    numbers = [float(value) for value in values if value != "" and value is not None]
    return mean(numbers) if numbers else ""


def _fieldnames(preferred: list[str], rows: list[dict[str, Any]]) -> list[str]:
    extras = sorted({key for row in rows for key in row if key not in preferred})
    return [*preferred, *extras]


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


def _split_doc_ids(value: Any) -> list[str]:
    seen = set()
    doc_ids = []
    for doc_id in str(value or "").split("|"):
        doc_id = doc_id.strip()
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            doc_ids.append(doc_id)
    return doc_ids


def _merge_doc_ids(existing: list[str], incoming: list[str]) -> list[str]:
    seen = set()
    merged = []
    for doc_id in [*existing, *incoming]:
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            merged.append(doc_id)
    return merged


def _query_id(scope: Any, chunk_id: Any) -> str:
    scope_text = _canonical_scope(_clean(scope))
    chunk_text = _clean(chunk_id)
    return f"{scope_text}||{chunk_text}" if scope_text and chunk_text else ""


def _split_query_id(query_id: str) -> tuple[str, str]:
    if "||" not in query_id:
        return "", query_id
    return tuple(query_id.split("||", maxsplit=1))  # type: ignore[return-value]


def _project_name_from_scope(scope: str) -> str:
    normalized = "".join(character.casefold() for character in scope if character.isalnum())
    if normalized.startswith("rn"):
        return "R&N"
    if normalized.startswith("fadhili"):
        return "Fadhili"
    if normalized.startswith("turkistan"):
        return "Turkistan"
    return scope.removesuffix("_ITB").replace("_", " ")


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
