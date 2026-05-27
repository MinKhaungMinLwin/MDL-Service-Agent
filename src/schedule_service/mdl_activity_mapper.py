"""Map ITB match outputs to CCPP guide schedule activities."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from schedule_service.guide_schedule_loader import DEFAULT_SCHEDULE_PATH, load_schedule_activities
from schedule_service.llm_validator import ScheduleLLMValidator
from schedule_service.models import Candidate, ScheduleActivity
from schedule_service.output_writer import write_mapping_outputs
from schedule_service.search.keyword_search import BM25Index
from schedule_service.search.reranker import rrf_candidates
from schedule_service.search.semantic_search import SemanticIndex


DEFAULT_OUTPUT_DIR = Path("output/schedule_service")
DEFAULT_RETRIEVE_K = 50
DEFAULT_TOP_K = 10


def map_file(
    input_csv: Path,
    schedule_activities: list[ScheduleActivity],
    output_dir: Path,
    retrieve_k: int = DEFAULT_RETRIEVE_K,
    top_k: int = DEFAULT_TOP_K,
    use_semantic: bool = True,
    use_llm: bool = True,
    limit: int = 0,
) -> tuple[Path, Path]:
    rows = _read_csv(input_csv)
    if limit > 0:
        rows = rows[:limit]
    if not rows:
        raise ValueError(f"No rows found in {input_csv}")

    bm25 = BM25Index([activity.target_text for activity in schedule_activities])
    semantic_index = SemanticIndex.build(schedule_activities, output_dir / "cache") if use_semantic else None
    llm_validator = ScheduleLLMValidator() if use_llm else None

    mapped_rows: list[dict[str, Any]] = []
    for row in rows:
        query_text = _query_text(row)
        candidates = _rank_candidates(query_text, schedule_activities, bm25, semantic_index, retrieve_k, top_k)
        llm_selection = llm_validator.select_activity(query_text, candidates) if llm_validator else _empty_llm_selection()
        mapped_rows.append(_format_output_row(input_csv, row, query_text, candidates, llm_selection, top_k))

    output_stem = input_csv.stem.replace("output_match_", "schedule_mapping_")
    if limit > 0:
        output_stem = f"{output_stem}_limit{limit}"
    return write_mapping_outputs(output_dir, output_stem, mapped_rows)


def _rank_candidates(
    query_text: str,
    activities: list[ScheduleActivity],
    bm25: BM25Index,
    semantic_index: SemanticIndex | None,
    retrieve_k: int,
    top_k: int,
) -> list[Candidate]:
    bm25_scores = bm25.score(query_text)
    semantic_scores = semantic_index.score(query_text) if semantic_index else [0.0] * len(activities)
    return rrf_candidates(
        activities=activities,
        bm25_scores=bm25_scores,
        semantic_scores=semantic_scores,
        retrieve_k=retrieve_k,
        top_k=top_k,
        has_semantic=semantic_index is not None,
    )


def _format_output_row(
    input_csv: Path,
    row: dict[str, str],
    query_text: str,
    candidates: list[Candidate],
    llm_selection: dict[str, str],
    top_k: int,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "source_file": input_csv.name,
        "document": row.get("Document", ""),
        "page": row.get("Page", ""),
        "search_query": query_text,
        "search_query_source": row.get("Search Query Source", ""),
        "keywords": row.get("Keywords", ""),
        "depth_context": row.get("Depth_Context", ""),
        **llm_selection,
    }

    for index in range(top_k):
        prefix = f"candidate_{index + 1}"
        if index >= len(candidates):
            output.update(_empty_candidate(prefix))
            continue

        candidate = candidates[index]
        activity = candidate.activity
        output.update(
            {
                f"{prefix}_activity_id": activity.activity_id,
                f"{prefix}_activity_name": activity.activity_name_clean or activity.activity_name,
                f"{prefix}_wbs_path": activity.wbs_path,
                f"{prefix}_start_date": activity.start_date,
                f"{prefix}_finish_date": activity.finish_date,
                f"{prefix}_target_text": activity.target_text,
                f"{prefix}_bm25_rank": candidate.bm25_rank or "",
                f"{prefix}_semantic_rank": candidate.semantic_rank or "",
                f"{prefix}_bm25_score": round(candidate.bm25_score, 6),
                f"{prefix}_semantic_score": round(candidate.semantic_score, 6),
                f"{prefix}_rrf_score": round(candidate.rrf_score, 6),
            }
        )
    return output


def _empty_llm_selection() -> dict[str, str]:
    return {
        "llm_selected_activity_id": "",
        "llm_selected_rank": "",
        "llm_confidence": "",
        "llm_reason": "",
        "llm_status": "",
    }


def _empty_candidate(prefix: str) -> dict[str, str]:
    fields = [
        "activity_id",
        "activity_name",
        "wbs_path",
        "start_date",
        "finish_date",
        "target_text",
        "bm25_rank",
        "semantic_rank",
        "bm25_score",
        "semantic_score",
        "rrf_score",
    ]
    return {f"{prefix}_{field}": "" for field in fields}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _query_text(row: dict[str, str]) -> str:
    query = row.get("Search Query", "").strip()
    if query:
        return query
    fallback = " ".join(
        value.strip()
        for value in [row.get("Search_Queries", ""), row.get("Keywords", ""), row.get("Depth_Context", "")]
        if value and value.strip()
    )
    return re.sub(r"\s+", " ", fallback).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Map ITB match outputs to guide schedule activities.")
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--retrieve-k", type=int, default=DEFAULT_RETRIEVE_K)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N rows from each input CSV.")
    parser.add_argument("--no-semantic", action="store_true", help="Disable semantic search and use BM25 only.")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM final selection.")
    parser.add_argument("inputs", nargs="+", type=Path, help="One or more output_match_*.csv files to map.")
    args = parser.parse_args()

    activities = load_schedule_activities(args.schedule)
    for input_csv in args.inputs:
        xlsx_path, json_path = map_file(
            input_csv=input_csv,
            schedule_activities=activities,
            output_dir=args.output_dir,
            retrieve_k=args.retrieve_k,
            top_k=args.top_k,
            use_semantic=not args.no_semantic,
            use_llm=not args.no_llm,
            limit=args.limit,
        )
        print(f"Wrote schedule mapping workbook: {xlsx_path}")
        print(f"Wrote schedule mapping JSON: {json_path}")


if __name__ == "__main__":
    main()
