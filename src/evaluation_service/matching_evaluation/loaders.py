"""Load ground truth and matching runs for ITB-to-MDL evaluation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from common.json_io import read_json

Qrels = dict[str, dict[str, int]]
Rankings = dict[str, list[str]]


def load_qrels(path: Path, sections: tuple[str, ...]) -> Qrels:
    """Load graded relevance judgments keyed by section and ITB chunk."""
    qrels: Qrels = {}
    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not {"section", "chunk_id", "mdl_doc_id", "relevance"} <= set(reader.fieldnames):
            raise ValueError("Ground truth CSV must contain section, chunk_id, mdl_doc_id, and relevance columns")
        for row in reader:
            section = str(row.get("section") or "").strip()
            chunk_id = str(row.get("chunk_id") or "").strip()
            doc_id = str(row.get("mdl_doc_id") or "").strip()
            if section not in sections or not chunk_id or not doc_id:
                continue
            query_id = f"{section}:{chunk_id}"
            relevance = _clamp_relevance(row.get("relevance"))
            existing = qrels.setdefault(query_id, {}).get(doc_id)
            if existing is not None and existing != relevance:
                raise ValueError(f"Conflicting relevance judgments for {query_id}:{doc_id}")
            qrels[query_id][doc_id] = relevance
    if not qrels:
        raise ValueError(f"No ground-truth judgments found for sections {', '.join(sections)}")
    return qrels


def load_matching_runs(
    matching_dir: Path,
    mode: str,
    sections: tuple[str, ...],
) -> tuple[Rankings, Rankings | None]:
    """Load post-cross-encoder rankings and optional retrieval rankings for one mode."""
    cross_encoder_rankings: Rankings = {}
    retrieval_rankings: Rankings = {}
    retrieval_artifacts_complete = True
    for section in sections:
        path = matching_dir / mode / f"output_match_all_projects_section{section}.json"
        records = read_json(path)
        if not isinstance(records, list):
            raise ValueError(f"Matching JSON must contain a list: {path}")
        for record in records:
            chunk_id = str(record.get("chunk_id") or "").strip()
            if not chunk_id:
                continue
            query_id = f"{section}:{chunk_id}"
            cross_encoder_rankings[query_id] = _candidate_doc_ids(record.get("candidates"))
            if "retrieval_candidates" not in record:
                retrieval_artifacts_complete = False
                continue
            retrieval_rankings[query_id] = _candidate_doc_ids(record.get("retrieval_candidates"))
    return cross_encoder_rankings, retrieval_rankings if retrieval_artifacts_complete else None


def discover_modes(matching_dir: Path) -> tuple[str, ...]:
    """Discover retrieval modes with matching artifacts."""
    modes = [mode for mode in ("keyword", "semantic", "hybrid") if (matching_dir / mode).is_dir()]
    if not modes:
        raise ValueError(f"No matching mode directories found in {matching_dir}")
    return tuple(modes)


def discover_sections(matching_dir: Path, modes: tuple[str, ...]) -> tuple[str, ...]:
    """Discover matching sections shared by all selected modes."""
    sections_by_mode = []
    prefix = "output_match_all_projects_section"
    suffix = ".json"
    for mode in modes:
        sections = {
            path.name.removeprefix(prefix).removesuffix(suffix)
            for path in (matching_dir / mode).glob(f"{prefix}*{suffix}")
        }
        sections_by_mode.append(sections)
    sections = set.intersection(*sections_by_mode) if sections_by_mode else set()
    if not sections:
        raise ValueError(f"No shared matching sections found for modes {', '.join(modes)}")
    return tuple(sorted(sections, key=_section_sort_key))


def _candidate_doc_ids(candidates: Any) -> list[str]:
    doc_ids = []
    seen = set()
    for candidate in candidates if isinstance(candidates, list) else []:
        doc_id = str(candidate.get("doc_id") or "").strip()
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            doc_ids.append(doc_id)
    return doc_ids


def _clamp_relevance(value: Any) -> int:
    return max(0, min(3, int(value)))


def _section_sort_key(section: str) -> tuple[int, int | str]:
    return (0, int(section)) if section.isdigit() else (1, section)
