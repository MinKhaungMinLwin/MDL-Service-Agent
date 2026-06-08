"""Build LLM-assisted ground truth for ITB to MDL matching."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from common.llm_json import parse_json_output

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_POSITIVE_JUDGE_PROMPT_PATH = PROMPTS_DIR / "matching_positive_judge.md"
DEFAULT_VERIFY_PROMPT_PATH = PROMPTS_DIR / "matching_relevance_verify.md"
GROUND_TRUTH_HEADER = [
    "section",
    "chunk_id",
    "mdl_doc_id",
    "relevance",
    "topic_match",
    "deliverable_match",
    "requirement_coverage",
    "context_fit",
    "reason",
    "verifier_relevance",
    "verifier_agrees",
]
HIGH_PRECISION_HEADER = [
    *GROUND_TRUTH_HEADER,
    "final_relevance",
    "label_status",
]
MDL_CANDIDATE_FIELDS = (
    "doc_id",
    "source_file",
    "document_no",
    "title",
    "equipment",
    "building",
    "system",
    "study_survey",
    "others",
    "deliverable",
    "text_content",
)
POOL_CANDIDATE_FIELDS = MDL_CANDIDATE_FIELDS
LLM_MDL_FIELDS = (
    "document_no",
    "title",
    "equipment",
    "building",
    "system",
    "study_survey",
    "others",
    "deliverable",
    "text_content",
)


@dataclass(frozen=True)
class EvaluationConfig:
    """Runtime settings for building matching ground truth."""

    model: str
    sections: tuple[str, ...] = ("6", "7")
    modes: tuple[str, ...] = ("keyword", "semantic", "hybrid")
    llm_retries: int = 2
    max_concurrency: int = 1
    max_itb_chunks: int = 0
    resume: bool = False
    batch_delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model is required")
        if not self.sections:
            raise ValueError("at least one section is required")
        if not self.modes:
            raise ValueError("at least one retrieval mode is required")
        if any(mode not in {"keyword", "semantic", "hybrid"} for mode in self.modes):
            raise ValueError("modes must contain only keyword, semantic, or hybrid")
        if self.llm_retries < 0:
            raise ValueError("llm_retries cannot be negative")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if self.max_itb_chunks < 0:
            raise ValueError("max_itb_chunks cannot be negative")
        if self.batch_delay_seconds < 0:
            raise ValueError("batch_delay_seconds cannot be negative")


class LLMResponseError(ValueError):
    """Raised when the LLM response does not match the expected schema."""


@dataclass(frozen=True)
class _JudgeTask:
    order: int
    pool_index: int
    pool_count: int
    chunk_index: int
    chunk_count: int
    pool: dict[str, Any]
    pairs: list[dict[str, Any]]


@dataclass(frozen=True)
class _VerifyTask:
    order: int
    pool_index: int
    pool_count: int
    payloads: list[dict[str, Any]]


class GroundTruthService:
    """Build candidate pools and produce LLM relevance judgments."""

    def __init__(
        self,
        config: EvaluationConfig,
        client: Any,
        judge_prompt: str,
        verify_prompt: str = "",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not verify_prompt:
            raise ValueError("verify_prompt is required")
        self.config = config
        self.client = client
        self.judge_prompt = judge_prompt
        self.verify_prompt = verify_prompt
        self.sleep = sleep

    def build_pool(self, extract_dir: Path, matching_dir: Path, pool_path: Path | None = None) -> list[dict[str, Any]]:
        """Build a candidate pool from existing matching artifacts."""
        itb_rows = limit_itb_rows(load_itb_rows(extract_dir, self.config.sections), self.config.max_itb_chunks)
        matching_records = load_matching_records(matching_dir, self.config.sections, self.config.modes)
        pools = build_candidate_pool(itb_rows, matching_records)
        if pool_path is not None:
            write_pool_csv(pool_path, pools)
        logger.info(
            "{} {} ITB candidate pools with {} MDL candidates{}",
            "Saved" if pool_path is not None else "Built",
            len(pools),
            _candidate_count(pools),
            f": {pool_path}" if pool_path is not None else "",
        )
        return pools

    def judge(
        self,
        pools: list[dict[str, Any]],
        resume_state_path: Path | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Select direct positive matches and verify them without writing output CSV files."""
        pairs = iter_judge_pairs(pools)
        pair_ids = {pair["judgment_id"] for pair in pairs}
        if self.config.resume:
            if resume_state_path is None:
                raise ValueError("resume_state_path is required when resume is enabled")
            judgments, verifications = read_resume_state(resume_state_path, pair_ids)
        else:
            judgments = []
            verifications = []
        judgments = self._select_positive_pools(pools, pairs, judgments, verifications, resume_state_path)
        verifications = self._verify_judgments(pairs, judgments, verifications, resume_state_path)
        return judgments, verifications

    def _select_positive_pools(
        self,
        pools: list[dict[str, Any]],
        pairs: list[dict[str, Any]],
        judgments: list[dict[str, Any]],
        verifications: list[dict[str, Any]],
        resume_state_path: Path | None,
    ) -> list[dict[str, Any]]:
        completed_pool_keys = read_completed_pool_keys(resume_state_path) if resume_state_path else set()
        completed_judgment_ids = {row.get("judgment_id") for row in judgments}
        pairs_by_pool = _group_pairs_by_pool(pairs)
        pools_to_judge = []
        for pool in pools:
            pool_key = _pool_key(pool)
            pool_pairs = [
                pair
                for pair in pairs_by_pool.get(pool_key, [])
                if pair["judgment_id"] not in completed_judgment_ids
            ]
            if pool_key not in completed_pool_keys and pool_pairs:
                pools_to_judge.append((pool, pool_pairs))
        logger.info(
            "Positive-only ground truth judge will process {} ITB pools ({} already completed, concurrency {})",
            len(pools_to_judge),
            len(completed_pool_keys),
            self.config.max_concurrency,
        )
        tasks = [
            _JudgeTask(
                order=index,
                pool_index=index,
                pool_count=len(pools_to_judge),
                chunk_index=1,
                chunk_count=1,
                pool=pool,
                pairs=pool_pairs,
            )
            for index, (pool, pool_pairs) in enumerate(pools_to_judge, start=1)
        ]
        task_pool_keys = {task.order: _pool_key(task.pool) for task in tasks}
        pair_order = _judgment_order(pairs)
        for _order, resolved in self._run_positive_tasks(tasks):
            judgments.extend(resolved)
            completed_pool_keys.add(task_pool_keys[_order])
            judgments.sort(key=lambda row: pair_order.get(row.get("judgment_id"), len(pair_order)))
            if resume_state_path is not None:
                write_resume_state(
                    resume_state_path,
                    judgments,
                    verifications,
                    completed_pools=completed_pool_keys,
                )
            self.sleep(self.config.batch_delay_seconds)
        logger.info("Completed {} positive relevance judgments", len(judgments))
        return judgments

    def _run_positive_tasks(self, tasks: list[_JudgeTask]) -> Iterator[tuple[int, list[dict[str, Any]]]]:
        if self.config.max_concurrency == 1:
            for task in tasks:
                yield task.order, self._run_positive_task(task)
            return

        completed: dict[int, list[dict[str, Any]]] = {}
        next_order = 1
        with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as executor:
            futures = {executor.submit(self._run_positive_task, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                completed[task.order] = future.result()
                while next_order in completed:
                    yield next_order, completed.pop(next_order)
                    next_order += 1

    def _run_positive_task(self, task: _JudgeTask) -> list[dict[str, Any]]:
        pool = task.pool
        logger.info(
            "Selecting positives for pool {}/{}: section {}, chunk {}, page {} ({} candidate{})",
            task.pool_index,
            task.pool_count,
            pool["section"],
            pool["chunk_id"],
            pool["itb"].get("page", ""),
            len(task.pairs),
            _plural(task.pairs),
        )
        payload = _build_judge_pool_payload(pool, task.pairs)
        return _run_with_retries(
            lambda: _resolve_positive_judgments(
                task.pairs,
                _run_llm_batch(self.client, self.config.model, self.judge_prompt, "pools", [payload]),
            ),
            retries=self.config.llm_retries,
            sleep=self.sleep,
            delay_seconds=self.config.batch_delay_seconds,
            description=f"positive judge section {pool['section']} chunk {pool['chunk_id']}",
        )

    def _verify_judgments(
        self,
        pairs: list[dict[str, Any]],
        judgments: list[dict[str, Any]],
        verifications: list[dict[str, Any]],
        resume_state_path: Path | None,
    ) -> list[dict[str, Any]]:
        completed_pool_keys = read_completed_pool_keys(resume_state_path) if resume_state_path else None
        pair_by_id = {pair["judgment_id"]: pair for pair in pairs}
        completed_ids = {row.get("judgment_id") for row in verifications}
        payloads = [
            {**pair_by_id[judgment["judgment_id"]], "proposed_judgment": judgment}
            for judgment in judgments
            if judgment["judgment_id"] in pair_by_id and judgment["judgment_id"] not in completed_ids
        ]
        payload_groups = list(_group_payloads_by_pool(payloads).values())
        logger.info(
            "Ground truth verification will process {} ITB pools with {} judgments "
            "({} already completed, concurrency {})",
            len(payload_groups),
            len(payloads),
            len(completed_ids),
            self.config.max_concurrency,
        )
        tasks = [
            _VerifyTask(
                order=index,
                pool_index=index,
                pool_count=len(payload_groups),
                payloads=payload_group,
            )
            for index, payload_group in enumerate(payload_groups, start=1)
        ]
        judgment_order = _judgment_order(judgments)
        for _order, resolved in self._run_verify_tasks(tasks):
            verifications.extend(resolved)
            verifications.sort(key=lambda row: judgment_order.get(row.get("judgment_id"), len(judgment_order)))
            if resume_state_path is not None:
                write_resume_state(
                    resume_state_path,
                    judgments,
                    verifications,
                    completed_pools=completed_pool_keys,
                )
            self.sleep(self.config.batch_delay_seconds)
        logger.info("Completed {} relevance verifications", len(verifications))
        return verifications

    def _run_verify_tasks(self, tasks: list[_VerifyTask]) -> Iterator[tuple[int, list[dict[str, Any]]]]:
        if self.config.max_concurrency == 1:
            for task in tasks:
                yield task.order, self._run_verify_task(task)
            return

        completed: dict[int, list[dict[str, Any]]] = {}
        next_order = 1
        with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as executor:
            futures = {executor.submit(self._run_verify_task, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                completed[task.order] = future.result()
                while next_order in completed:
                    yield next_order, completed.pop(next_order)
                    next_order += 1

    def _run_verify_task(self, task: _VerifyTask) -> list[dict[str, Any]]:
        logger.info(
            "Verifying pool {}/{}: section {}, chunk {} ({} positive judgment{})",
            task.pool_index,
            task.pool_count,
            task.payloads[0]["section"] if task.payloads else "",
            task.payloads[0]["chunk_id"] if task.payloads else "",
            len(task.payloads),
            _plural(task.payloads),
        )
        payload = _build_verify_pool_payload(task.payloads)
        return _run_with_retries(
            lambda: _resolve_verifications(
                task.payloads,
                _run_llm_batch(self.client, self.config.model, self.verify_prompt, "verification_pools", [payload]),
            ),
            retries=self.config.llm_retries,
            sleep=self.sleep,
            delay_seconds=self.config.batch_delay_seconds,
            description=f"verify section {payload.get('section', '')} chunk {payload.get('chunk_id', '')}",
        )


def load_itb_rows(extract_dir: Path, sections: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """Load extracted ITB rows keyed by section and chunk ID."""
    rows_by_key = {}
    for section in sections:
        path = extract_dir / f"itb_extraction_section{section}.csv"
        with open(path, newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                chunk_id = str(row.get("Chunk ID") or "").strip()
                if chunk_id:
                    rows_by_key[f"{section}:{chunk_id}"] = row
    return rows_by_key


def limit_itb_rows(itb_rows: dict[str, dict[str, Any]], max_itb_chunks: int) -> dict[str, dict[str, Any]]:
    """Keep the first N ITB rows in section/chunk order when a test limit is set."""
    if max_itb_chunks <= 0:
        return itb_rows
    return {
        key: itb_rows[key]
        for key in sorted(itb_rows, key=_section_chunk_sort_key)[:max_itb_chunks]
    }


def load_matching_records(
    matching_dir: Path,
    sections: tuple[str, ...],
    modes: tuple[str, ...],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Load matching CSV records keyed by section and retrieval mode."""
    records_by_source = {}
    for section in sections:
        for mode in modes:
            path = matching_dir / mode / f"output_match_all_projects_section{section}.csv"
            records_by_source[(section, mode)] = read_matching_csv_records(path)
    return records_by_source


def build_candidate_pool(
    itb_rows: dict[str, dict[str, Any]],
    records_by_source: dict[tuple[str, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Merge and deduplicate top MDL candidates from each retrieval mode."""
    pools_by_key: dict[str, dict[str, Any]] = {}
    for (section, _mode), records in records_by_source.items():
        for record in records:
            chunk_id = str(record.get("chunk_id") or "").strip()
            key = f"{section}:{chunk_id}"
            itb_row = itb_rows.get(key)
            if not chunk_id or itb_row is None:
                continue
            pool = pools_by_key.setdefault(key, _build_pool_record(section, record, itb_row))
            candidates_by_id = pool.pop("_candidates_by_id")
            for candidate in record.get("candidates", []):
                candidate_key = _candidate_key(candidate)
                if not candidate_key:
                    continue
                candidates_by_id.setdefault(candidate_key, _build_pool_candidate(candidate))
            pool["_candidates_by_id"] = candidates_by_id

    pools = []
    for key in sorted(pools_by_key):
        pool = pools_by_key[key]
        candidates = list(pool.pop("_candidates_by_id").values())
        random.Random(_stable_seed(key)).shuffle(candidates)
        pool["candidates"] = candidates
        pools.append(pool)
    return pools


def iter_judge_pairs(pools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten candidate pools into blind ITB to MDL pairs for the LLM judge."""
    pairs = []
    for pool in pools:
        for candidate in pool["candidates"]:
            pairs.append(
                {
                    "judgment_id": f"{pool['section']}:{pool['chunk_id']}:{candidate['doc_id']}",
                    "section": pool["section"],
                    "chunk_id": pool["chunk_id"],
                    "itb": _build_llm_itb(pool["itb"]),
                    "mdl": {
                        field: candidate.get(field, "")
                        for field in MDL_CANDIDATE_FIELDS
                    },
                }
            )
    return pairs


def _build_judge_pool_payload(pool: dict[str, Any], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "section": pool["section"],
        "chunk_id": pool["chunk_id"],
        "itb": _build_llm_itb(pool["itb"]),
        "candidates": [
            {
                "judgment_id": pair["judgment_id"],
                "mdl": _build_llm_mdl(pair["mdl"]),
            }
            for pair in pairs
        ],
    }


def _build_verify_pool_payload(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    if not payloads:
        return {"positive_candidates": []}
    first = payloads[0]
    return {
        "section": first["section"],
        "chunk_id": first["chunk_id"],
        "itb": _build_llm_itb(first["itb"]),
        "positive_candidates": [
            {
                "judgment_id": payload["judgment_id"],
                "mdl": _build_llm_mdl(payload["mdl"]),
                "proposed_judgment": payload["proposed_judgment"],
            }
            for payload in payloads
        ],
    }


def read_matching_csv_records(path: Path) -> list[dict[str, Any]]:
    records = []
    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        candidate_indexes = _matched_candidate_indexes(fieldnames)
        for row in reader:
            records.append(
                {
                    "document": row.get("Document", ""),
                    "chunk_id": row.get("Chunk ID", ""),
                    "page": row.get("Page", ""),
                    "depths": {
                        field: row.get(field, "")
                        for field in ("1st Depth", "2nd Depth", "3rd Depth", "4th Depth", "5th Depth")
                        if str(row.get(field, "")).strip()
                    },
                    "keywords": row.get("Keywords", ""),
                    "chunk_text": row.get("Chunk Text", ""),
                    "candidates": [
                        candidate
                        for index in candidate_indexes
                        if (candidate := _candidate_from_matching_row(row, index))
                    ],
                }
            )
    return records


def write_pool_csv(path: Path, pools: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["section", "chunk_id", "candidate_count", "candidate_doc_ids"]
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=header)
        writer.writeheader()
        for pool in pools:
            writer.writerow(
                {
                    "section": pool.get("section", ""),
                    "chunk_id": pool.get("chunk_id", ""),
                    "candidate_count": len(pool.get("candidates", [])),
                    "candidate_doc_ids": "|".join(
                        str(candidate.get("doc_id", "")).strip()
                        for candidate in pool.get("candidates", [])
                        if str(candidate.get("doc_id", "")).strip()
                    ),
                }
            )


def read_resume_state(resume_state_path: Path, pair_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not resume_state_path.exists():
        return [], []
    rows = _read_resume_rows(resume_state_path)
    judgments = [row for row in rows if row.get("record_type") == "judgment" and row.get("judgment_id") in pair_ids]
    verifications = [
        row for row in rows if row.get("record_type") == "verification" and row.get("judgment_id") in pair_ids
    ]
    return judgments, verifications


def read_completed_pool_keys(resume_state_path: Path) -> set[tuple[str, str]]:
    if not resume_state_path.exists():
        return set()
    return {
        (str(row.get("section")), str(row.get("chunk_id")))
        for row in _read_resume_rows(resume_state_path)
        if row.get("section") and row.get("chunk_id")
        and row.get("record_type") == "completed_pool"
    }


def write_resume_state(
    resume_state_path: Path,
    judgments: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
    completed_pools: set[tuple[str, str]] | None = None,
) -> None:
    rows = []
    for judgment in judgments:
        rows.append({"record_type": "judgment", **judgment})
    for verification in verifications:
        rows.append({"record_type": "verification", **verification})
    if completed_pools is not None:
        rows.extend(
            {"record_type": "completed_pool", "section": section, "chunk_id": chunk_id}
            for section, chunk_id in sorted(completed_pools)
        )
    _write_resume_rows(resume_state_path, rows)


def build_verified_positive_ground_truth_rows(
    judgments: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build verified positive rows for the canonical ground-truth file."""
    verification_by_id = {row.get("judgment_id"): row for row in verifications}
    rows = []
    for judgment in judgments:
        verification = verification_by_id.get(judgment.get("judgment_id"), {})
        if not verification.get("agrees"):
            continue
        if _clamp_int(judgment.get("relevance"), 0, 3) != 3:
            continue
        if _clamp_int(verification.get("relevance"), 0, 3) != 3:
            continue
        rows.append(
            {
                **_build_ground_truth_row(judgment, verification),
                "final_relevance": 3,
                "label_status": "positive",
            }
        )
    return _dedupe_ground_truth_rows(rows)


def load_positive_ground_truth_rows(paths: tuple[Path, ...]) -> list[dict[str, Any]]:
    """Load trusted positive rows from existing ground-truth CSV files."""
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        with open(path, newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            for row in reader:
                normalized = _normalize_positive_ground_truth_row(row)
                if not normalized:
                    continue
                rows_by_key.setdefault(_ground_truth_row_key(normalized), normalized)
    return [rows_by_key[key] for key in sorted(rows_by_key)]


def write_merged_positive_ground_truth(output_path: Path, input_paths: tuple[Path, ...]) -> int:
    """Write a deduplicated positive-only ground-truth CSV from verified inputs."""
    rows = _merge_positive_ground_truth_rows(load_positive_ground_truth_rows(input_paths))
    _write_high_precision_rows(output_path, rows)
    logger.info("Saved {} merged positive ground-truth rows: {}", len(rows), output_path)
    return len(rows)


def write_merged_positive_ground_truth_rows(output_path: Path, rows: list[dict[str, Any]]) -> int:
    """Merge verified positive rows into a deduplicated positive-only ground-truth CSV."""
    existing_rows = load_positive_ground_truth_rows((output_path,)) if output_path.exists() else []
    merged_rows = _merge_positive_ground_truth_rows([*existing_rows, *rows])
    _write_high_precision_rows(output_path, merged_rows)
    logger.info("Saved {} merged positive ground-truth rows: {}", len(merged_rows), output_path)
    return len(merged_rows)


def _merge_positive_ground_truth_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        normalized = _normalize_positive_ground_truth_row(row)
        if normalized:
            rows_by_key.setdefault(_ground_truth_row_key(normalized), normalized)
    return [rows_by_key[key] for key in sorted(rows_by_key)]


def _write_high_precision_rows(output_path: Path, rows: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=HIGH_PRECISION_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def _dedupe_ground_truth_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        rows_by_key.setdefault(_ground_truth_row_key(row), row)
    return [rows_by_key[key] for key in sorted(rows_by_key)]


def _run_llm_batch(
    client: Any,
    model: str,
    system_prompt: str,
    payload_name: str,
    payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({payload_name: payloads}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_completion_tokens=_max_completion_tokens(payloads),
        response_format={"type": "json_object"},
    )
    try:
        parsed = parse_json_output(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as exc:
        raise LLMResponseError("LLM response is not valid JSON") from exc
    results = parsed.get("results")
    if not isinstance(results, list):
        raise LLMResponseError("LLM response must contain a results list")
    if not all(isinstance(item, dict) for item in results):
        raise LLMResponseError("LLM results must be JSON objects")
    return results


def _max_completion_tokens(payloads: list[dict[str, Any]]) -> int:
    result_count = sum(
        len(payload.get("candidates", [])) or len(payload.get("positive_candidates", [])) or 1
        for payload in payloads
    )
    return min(8192, 1024 * result_count)


def _candidate_count(pools: list[dict[str, Any]]) -> int:
    return sum(len(pool.get("candidates", [])) for pool in pools)


def _build_llm_itb(itb: dict[str, Any]) -> dict[str, Any]:
    return _compact_context(
        {
            "section": itb.get("section", ""),
            "chunk_id": itb.get("chunk_id", ""),
            "hierarchy_context": itb.get("hierarchy_context", ""),
            "depths": itb.get("depths", {}),
            "keywords": itb.get("keywords", ""),
            "chunk_text": itb.get("chunk_text", ""),
        }
    )


def _build_llm_mdl(mdl: dict[str, Any]) -> dict[str, Any]:
    return _compact_context({field: mdl.get(field, "") for field in LLM_MDL_FIELDS})


def _compact_context(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if value not in ("", None, {}) and value != []
    }


def _matched_candidate_indexes(fieldnames: list[str]) -> list[int]:
    indexes = []
    prefix = "Matched_Doc_"
    suffix = "_Doc_ID"
    for field in fieldnames:
        if field.startswith(prefix) and field.endswith(suffix):
            raw_index = field[len(prefix) : -len(suffix)]
            if raw_index.isdigit():
                indexes.append(int(raw_index))
    return sorted(indexes)


def _candidate_from_matching_row(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    prefix = f"Matched_Doc_{index}"
    doc_id = str(row.get(f"{prefix}_Doc_ID") or "").strip()
    if not doc_id:
        return None
    return {
        "doc_id": doc_id,
        "source_file": row.get(f"{prefix}_Source_File", ""),
        "document_no": row.get(f"{prefix}_Document_No", ""),
        "title": row.get(f"{prefix}_Title", ""),
        "equipment": row.get(f"{prefix}_Equipment", ""),
        "building": row.get(f"{prefix}_Building", ""),
        "system": row.get(f"{prefix}_System", ""),
        "study_survey": row.get(f"{prefix}_Study_Survey", ""),
        "others": row.get(f"{prefix}_Others", ""),
        "deliverable": row.get(f"{prefix}_Deliverable", ""),
        "text_content": row.get(f"{prefix}_Text_Content", ""),
    }


def _read_resume_rows(path: Path) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        return [dict(row) for row in csv.DictReader(file)]


def _write_resume_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _resume_fieldnames(rows)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _resume_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "record_type",
        "judgment_id",
        "section",
        "chunk_id",
        "mdl_doc_id",
        "relevance",
        "topic_match",
        "deliverable_match",
        "requirement_coverage",
        "context_fit",
        "reason",
        "agrees",
    ]
    extras = sorted({key for row in rows for key in row if key not in preferred})
    return preferred + extras


def _normalize_positive_ground_truth_row(row: dict[str, Any]) -> dict[str, Any] | None:
    section = str(row.get("section") or "").strip()
    chunk_id = str(row.get("chunk_id") or "").strip()
    doc_id = str(row.get("mdl_doc_id") or "").strip()
    if not section or not chunk_id or not doc_id or not _is_positive_ground_truth_row(row):
        return None
    normalized = {field: row.get(field, "") for field in HIGH_PRECISION_HEADER}
    normalized.update(
        {
            "section": section,
            "chunk_id": chunk_id,
            "mdl_doc_id": doc_id,
            "relevance": 3,
            "verifier_relevance": 3,
            "verifier_agrees": True,
            "final_relevance": 3,
            "label_status": "positive",
        }
    )
    return normalized


def _is_positive_ground_truth_row(row: dict[str, Any]) -> bool:
    label_status = str(row.get("label_status") or "").strip().lower()
    try:
        final_relevance = _clamp_int(row.get("final_relevance"), 0, 3)
    except (TypeError, ValueError):
        return False
    return final_relevance == 3 and label_status == "positive"


def _ground_truth_row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("section", "")), str(row.get("chunk_id", "")), str(row.get("mdl_doc_id", "")))


def _build_pool_record(section: str, record: dict[str, Any], itb_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": section,
        "chunk_id": record["chunk_id"],
        "itb": {
            "document": itb_row.get("Document", record.get("document", "")),
            "chunk_id": record["chunk_id"],
            "page": itb_row.get("Page", record.get("page", "")),
            "section": itb_row.get("Section", section),
            "hierarchy_context": itb_row.get("Hierarchy Context", ""),
            "depths": _build_itb_depths(itb_row, record.get("depths", {})),
            "keywords": itb_row.get("Keywords", record.get("keywords", "")),
            "chunk_text": itb_row.get("Chunk Text", ""),
        },
        "_candidates_by_id": {},
    }


def _build_pool_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        field: candidate[field]
        for field in POOL_CANDIDATE_FIELDS
        if field in candidate
    }


def _build_itb_depths(itb_row: dict[str, Any], fallback_depths: dict[str, Any]) -> dict[str, Any]:
    depths = {
        field: itb_row.get(field, "")
        for field in ("1st Depth", "2nd Depth", "3rd Depth", "4th Depth", "5th Depth")
        if str(itb_row.get(field, "")).strip()
    }
    return depths or fallback_depths


def _candidate_key(candidate: dict[str, Any]) -> str:
    document_values = [str(candidate.get(field) or "").strip() for field in ("source_file", "document_no", "title")]
    if all(document_values):
        return f"document:{'|'.join(document_values)}"
    doc_id = str(candidate.get("doc_id") or "").strip()
    return f"doc_id:{doc_id}" if doc_id else ""


def _section_chunk_sort_key(key: str) -> tuple[int, int | str, str]:
    section, chunk_id = key.split(":", maxsplit=1)
    section_key: int | str = int(section) if section.isdigit() else section
    return (0 if section.isdigit() else 1, section_key, chunk_id)


def _build_ground_truth_row(judgment: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": judgment.get("section", ""),
        "chunk_id": judgment.get("chunk_id", ""),
        "mdl_doc_id": judgment.get("mdl_doc_id", ""),
        "relevance": _clamp_int(judgment.get("relevance"), 0, 3),
        "topic_match": judgment.get("topic_match", ""),
        "deliverable_match": judgment.get("deliverable_match", ""),
        "requirement_coverage": judgment.get("requirement_coverage", ""),
        "context_fit": judgment.get("context_fit", ""),
        "reason": judgment.get("reason", ""),
        "verifier_relevance": verification.get("relevance", ""),
        "verifier_agrees": verification.get("agrees", ""),
    }


def _resolve_positive_judgments(
    pairs: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not results:
        raise LLMResponseError("LLM response must include a positive selection result")
    pairs_by_id = {pair["judgment_id"]: pair for pair in pairs}
    positive_ids = []
    reasons = {}
    for result in results:
        raw_ids = result.get("positive_judgment_ids", [])
        if not isinstance(raw_ids, list):
            raise LLMResponseError("positive_judgment_ids must be a list")
        positive_ids.extend(str(judgment_id) for judgment_id in raw_ids)
        raw_reasons = result.get("reasons", {})
        if isinstance(raw_reasons, dict):
            reasons.update({str(key): str(value) for key, value in raw_reasons.items()})
    unknown_ids = [judgment_id for judgment_id in positive_ids if judgment_id not in pairs_by_id]
    if unknown_ids:
        raise LLMResponseError(f"LLM response returned unknown positives: {_format_missing_ids(unknown_ids)}")
    resolved = []
    seen = set()
    for judgment_id in positive_ids:
        if judgment_id in seen:
            continue
        seen.add(judgment_id)
        pair = pairs_by_id[judgment_id]
        resolved.append(
            {
                "judgment_id": judgment_id,
                "section": pair["section"],
                "chunk_id": pair["chunk_id"],
                "mdl_doc_id": pair["mdl"]["doc_id"],
                "topic_match": 3,
                "deliverable_match": 3,
                "requirement_coverage": 3,
                "context_fit": 3,
                "relevance": 3,
                "reason": reasons.get(judgment_id, "Selected as a direct positive match."),
            }
        )
    return resolved


def _resolve_verifications(
    payloads: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results_by_id = {str(row.get("judgment_id") or ""): row for row in results}
    missing_ids = [payload["judgment_id"] for payload in payloads if payload["judgment_id"] not in results_by_id]
    if missing_ids:
        raise LLMResponseError(f"LLM response missing verifications: {_format_missing_ids(missing_ids)}")
    resolved = []
    for payload in payloads:
        judgment_id = payload["judgment_id"]
        result = results_by_id[judgment_id]
        resolved.append({**_normalize_verification(result), "judgment_id": judgment_id})
    return resolved


def _run_with_retries(
    operation: Callable[[], list[dict[str, Any]]],
    retries: int,
    sleep: Callable[[float], None],
    delay_seconds: float,
    description: str,
) -> list[dict[str, Any]]:
    for attempt in range(retries + 1):
        try:
            return operation()
        except LLMResponseError as exc:
            if attempt >= retries:
                raise
            logger.warning(
                "{} failed on attempt {}/{}: {}. Retrying...",
                description,
                attempt + 1,
                retries + 1,
                exc,
            )
            sleep(delay_seconds)
    raise AssertionError("unreachable")


def _format_missing_ids(missing_ids: list[str]) -> str:
    preview = missing_ids[:5]
    suffix = "" if len(missing_ids) <= len(preview) else f", ... ({len(missing_ids)} total)"
    return ", ".join(preview) + suffix


def _judgment_order(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {str(row["judgment_id"]): index for index, row in enumerate(rows)}


def _group_pairs_by_pool(pairs: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    pairs_by_pool: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for pair in pairs:
        pairs_by_pool.setdefault(_pool_key(pair), []).append(pair)
    return pairs_by_pool


def _group_payloads_by_pool(payloads: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    payloads_by_pool: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for payload in payloads:
        payloads_by_pool.setdefault(_pool_key(payload), []).append(payload)
    return payloads_by_pool


def _pool_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row["section"]), str(row["chunk_id"]))


def _judgment_pool_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("section", "")), str(row.get("chunk_id", "")))


def _normalize_verification(verification: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(verification)
    normalized.pop("confidence", None)
    if normalized.get("relevance") != "":
        normalized["relevance"] = _clamp_int(normalized.get("relevance"), 0, 3)
    normalized["agrees"] = normalized.get("agrees") is True
    return normalized


def _stable_seed(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _plural(items: list[Any]) -> str:
    return "" if len(items) == 1 else "s"
