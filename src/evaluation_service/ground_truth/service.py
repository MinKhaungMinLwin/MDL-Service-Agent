"""Build LLM-assisted ground truth for ITB to MDL matching."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from common.json_io import read_json, read_json_list, write_json
from common.llm_json import parse_json_output

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_JUDGE_PROMPT_PATH = PROMPTS_DIR / "matching_relevance_judge.md"
DEFAULT_VERIFY_PROMPT_PATH = PROMPTS_DIR / "matching_relevance_verify.md"
GROUND_TRUTH_HEADER = [
    "section",
    "chunk_id",
    "mdl_doc_id",
    "relevance",
    "confidence",
    "topic_match",
    "deliverable_match",
    "requirement_coverage",
    "context_fit",
    "reason",
    "verifier_relevance",
    "verifier_confidence",
    "verifier_agrees",
]


@dataclass(frozen=True)
class EvaluationConfig:
    """Runtime settings for building matching ground truth."""

    model: str
    sections: tuple[str, ...] = ("6", "7")
    modes: tuple[str, ...] = ("keyword", "semantic", "hybrid")
    pool_top_k: int = 20
    batch_size: int = 5
    judge_candidates_per_call: int = 25
    llm_retries: int = 2
    max_concurrency: int = 1
    verify: bool = False
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
        if self.pool_top_k <= 0:
            raise ValueError("pool_top_k must be positive")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.judge_candidates_per_call <= 0:
            raise ValueError("judge_candidates_per_call must be positive")
        if self.llm_retries < 0:
            raise ValueError("llm_retries cannot be negative")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
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
    batch_index: int
    batch_count: int
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
        if config.verify and not verify_prompt:
            raise ValueError("verify_prompt is required when verification is enabled")
        self.config = config
        self.client = client
        self.judge_prompt = judge_prompt
        self.verify_prompt = verify_prompt
        self.sleep = sleep

    def build_pool(self, extract_dir: Path, matching_dir: Path, pool_path: Path) -> list[dict[str, Any]]:
        """Build and persist a candidate pool from existing matching artifacts."""
        itb_rows = load_itb_rows(extract_dir, self.config.sections)
        matching_records = load_matching_records(matching_dir, self.config.sections, self.config.modes)
        pools = build_candidate_pool(itb_rows, matching_records, self.config.pool_top_k)
        write_json(pool_path, pools)
        logger.info(
            "Saved {} ITB candidate pools with {} MDL candidates: {}",
            len(pools),
            _candidate_count(pools),
            pool_path,
        )
        return pools

    def judge_to_files(
        self,
        pools: list[dict[str, Any]],
        judgments_path: Path,
        verifications_path: Path,
        ground_truth_path: Path,
    ) -> None:
        """Generate judgments, optionally verify all rows, and write ground truth."""
        pairs = iter_judge_pairs(pools)
        pair_ids = {pair["judgment_id"] for pair in pairs}
        judgments = [row for row in read_json_list(judgments_path) if row.get("judgment_id") in pair_ids]
        verifications = [row for row in read_json_list(verifications_path) if row.get("judgment_id") in pair_ids]
        if not self.config.resume:
            judgments = []
            verifications = []
        judgments = self._judge_pools(pools, pairs, judgments, judgments_path, ground_truth_path)
        if self.config.verify:
            verifications = self._verify_judgments(pairs, judgments, verifications, verifications_path)
        write_ground_truth(ground_truth_path, judgments, verifications)
        logger.info("Saved silver ground truth: {}", ground_truth_path)

    def _judge_pools(
        self,
        pools: list[dict[str, Any]],
        pairs: list[dict[str, Any]],
        judgments: list[dict[str, Any]],
        judgments_path: Path,
        ground_truth_path: Path,
    ) -> list[dict[str, Any]]:
        completed_ids = {row.get("judgment_id") for row in judgments}
        pairs_by_pool = _group_pairs_by_pool(pairs)
        pools_to_judge = []
        candidate_count = 0
        for pool in pools:
            pool_pairs = [
                pair
                for pair in pairs_by_pool.get(_pool_key(pool), [])
                if pair["judgment_id"] not in completed_ids
            ]
            if pool_pairs:
                pools_to_judge.append((pool, pool_pairs))
                candidate_count += len(pool_pairs)
        logger.info(
            "Ground truth judge will process {} candidates across {} ITB pools ({} already completed, max {} candidates per call, concurrency {})",
            candidate_count,
            len(pools_to_judge),
            len(completed_ids),
            self.config.judge_candidates_per_call,
            self.config.max_concurrency,
        )
        tasks = []
        task_order = 0
        for pool_index, (pool, pool_pairs) in enumerate(pools_to_judge, start=1):
            pair_chunks = _chunked(pool_pairs, self.config.judge_candidates_per_call)
            for chunk_index, pair_chunk in enumerate(pair_chunks, start=1):
                task_order += 1
                tasks.append(
                    _JudgeTask(
                        order=task_order,
                        pool_index=pool_index,
                        pool_count=len(pools_to_judge),
                        chunk_index=chunk_index,
                        chunk_count=len(pair_chunks),
                        pool=pool,
                        pairs=pair_chunk,
                    )
                )
        pair_order = _judgment_order(pairs)
        for _order, resolved in self._run_judge_tasks(tasks):
            judgments.extend(resolved)
            judgments.sort(key=lambda row: pair_order.get(row.get("judgment_id"), len(pair_order)))
            write_json(judgments_path, judgments)
            write_ground_truth(ground_truth_path, judgments, [])
            self.sleep(self.config.batch_delay_seconds)
        logger.info("Completed {} relevance judgments", len(judgments))
        return judgments

    def _run_judge_tasks(self, tasks: list[_JudgeTask]) -> Iterator[tuple[int, list[dict[str, Any]]]]:
        if self.config.max_concurrency == 1:
            for task in tasks:
                yield task.order, self._run_judge_task(task)
            return

        completed: dict[int, list[dict[str, Any]]] = {}
        next_order = 1
        with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as executor:
            futures = {executor.submit(self._run_judge_task, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                completed[task.order] = future.result()
                while next_order in completed:
                    yield next_order, completed.pop(next_order)
                    next_order += 1

    def _run_judge_task(self, task: _JudgeTask) -> list[dict[str, Any]]:
        pool = task.pool
        logger.info(
            "Judging pool {}/{} chunk {}/{}: section {}, chunk {}, page {} ({} candidate{})",
            task.pool_index,
            task.pool_count,
            task.chunk_index,
            task.chunk_count,
            pool["section"],
            pool["chunk_id"],
            pool["itb"].get("page", ""),
            len(task.pairs),
            _plural(task.pairs),
        )
        payload = _build_judge_pool_payload(pool, task.pairs)
        return _run_with_retries(
            lambda: _resolve_judgments(
                task.pairs,
                _run_llm_batch(self.client, self.config.model, self.judge_prompt, "pools", [payload]),
            ),
            retries=self.config.llm_retries,
            sleep=self.sleep,
            delay_seconds=self.config.batch_delay_seconds,
            description=(
                f"judge section {pool['section']} chunk {pool['chunk_id']} "
                f"pool {task.pool_index}/{task.pool_count} chunk {task.chunk_index}/{task.chunk_count}"
            ),
        )

    def _verify_judgments(
        self,
        pairs: list[dict[str, Any]],
        judgments: list[dict[str, Any]],
        verifications: list[dict[str, Any]],
        verifications_path: Path,
    ) -> list[dict[str, Any]]:
        pair_by_id = {pair["judgment_id"]: pair for pair in pairs}
        completed_ids = {row.get("judgment_id") for row in verifications}
        payloads = [
            {**pair_by_id[judgment["judgment_id"]], "proposed_judgment": judgment}
            for judgment in judgments
            if judgment["judgment_id"] in pair_by_id and judgment["judgment_id"] not in completed_ids
        ]
        batches = _chunked(payloads, self.config.batch_size)
        logger.info(
            "Ground truth verification will process {} judgments ({} already completed, concurrency {})",
            len(payloads),
            len(completed_ids),
            self.config.max_concurrency,
        )
        tasks = [
            _VerifyTask(
                order=index,
                batch_index=index,
                batch_count=len(batches),
                payloads=batch,
            )
            for index, batch in enumerate(batches, start=1)
        ]
        judgment_order = _judgment_order(judgments)
        for _order, resolved in self._run_verify_tasks(tasks):
            verifications.extend(resolved)
            verifications.sort(key=lambda row: judgment_order.get(row.get("judgment_id"), len(judgment_order)))
            write_json(verifications_path, verifications)
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
            "Verifying batch {}/{} ({} judgment{})",
            task.batch_index,
            task.batch_count,
            len(task.payloads),
            _plural(task.payloads),
        )
        return _run_with_retries(
            lambda: _resolve_verifications(
                task.payloads,
                _run_llm_batch(self.client, self.config.model, self.verify_prompt, "judgments", task.payloads),
            ),
            retries=self.config.llm_retries,
            sleep=self.sleep,
            delay_seconds=self.config.batch_delay_seconds,
            description=f"verify batch {task.batch_index}/{task.batch_count}",
        )


def load_itb_rows(extract_dir: Path, sections: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """Load extracted ITB rows keyed by section and chunk ID."""
    rows_by_key = {}
    for section in sections:
        path = extract_dir / f"output_itb_section{section}_focused.csv"
        with open(path, newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                chunk_id = str(row.get("Chunk ID") or "").strip()
                if chunk_id:
                    rows_by_key[f"{section}:{chunk_id}"] = row
    return rows_by_key


def load_matching_records(
    matching_dir: Path,
    sections: tuple[str, ...],
    modes: tuple[str, ...],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Load matching JSON records keyed by section and retrieval mode."""
    records_by_source = {}
    for section in sections:
        for mode in modes:
            path = matching_dir / mode / f"output_match_all_projects_section{section}.json"
            records_by_source[(section, mode)] = read_json(path)
    return records_by_source


def build_candidate_pool(
    itb_rows: dict[str, dict[str, Any]],
    records_by_source: dict[tuple[str, str], list[dict[str, Any]]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Merge and deduplicate top MDL candidates from each retrieval mode."""
    pools_by_key: dict[str, dict[str, Any]] = {}
    for (section, mode), records in records_by_source.items():
        for record in records:
            chunk_id = str(record.get("chunk_id") or "").strip()
            key = f"{section}:{chunk_id}"
            itb_row = itb_rows.get(key)
            if not chunk_id or itb_row is None:
                continue
            pool = pools_by_key.setdefault(key, _build_pool_record(section, record, itb_row))
            candidates_by_id = pool.pop("_candidates_by_id")
            for rank, candidate in enumerate(record.get("candidates", [])[:top_k], start=1):
                doc_id = str(candidate.get("doc_id") or "").strip()
                if not doc_id:
                    continue
                pooled_candidate = candidates_by_id.setdefault(
                    doc_id,
                    {**candidate, "source_modes": [], "source_ranks": {}},
                )
                if mode not in pooled_candidate["source_modes"]:
                    pooled_candidate["source_modes"].append(mode)
                pooled_candidate["source_ranks"][mode] = rank
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
                    "itb": pool["itb"],
                    "mdl": {
                        field: candidate.get(field, "")
                        for field in (
                            "doc_id",
                            "title",
                            "equipment",
                            "building",
                            "system",
                            "study_survey",
                            "others",
                            "deliverable",
                        )
                    },
                }
            )
    return pairs


def _build_judge_pool_payload(pool: dict[str, Any], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "section": pool["section"],
        "chunk_id": pool["chunk_id"],
        "itb": pool["itb"],
        "candidates": [
            {
                "judgment_id": pair["judgment_id"],
                "mdl": pair["mdl"],
            }
            for pair in pairs
        ],
    }


def write_ground_truth(
    ground_truth_path: Path,
    judgments: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
) -> None:
    """Write silver ground truth."""
    verification_by_id = {row.get("judgment_id"): row for row in verifications}
    rows = [
        _build_ground_truth_row(judgment, verification_by_id.get(judgment.get("judgment_id"), {}))
        for judgment in judgments
    ]
    ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ground_truth_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=GROUND_TRUTH_HEADER)
        writer.writeheader()
        writer.writerows(rows)


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
    result_count = sum(len(payload.get("candidates", [])) or 1 for payload in payloads)
    return min(8192, 1024 * result_count)


def _candidate_count(pools: list[dict[str, Any]]) -> int:
    return sum(len(pool.get("candidates", [])) for pool in pools)


def _build_pool_record(section: str, record: dict[str, Any], itb_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": section,
        "chunk_id": record["chunk_id"],
        "itb": {
            "document": record.get("document", ""),
            "page": record.get("page", ""),
            "depths": record.get("depths", {}),
            "keywords": record.get("keywords", ""),
            "chunk_text": itb_row.get("Chunk Text", ""),
        },
        "_candidates_by_id": {},
    }


def _build_ground_truth_row(judgment: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": judgment.get("section", ""),
        "chunk_id": judgment.get("chunk_id", ""),
        "mdl_doc_id": judgment.get("mdl_doc_id", ""),
        "relevance": _clamp_int(judgment.get("relevance"), 0, 3),
        "confidence": judgment.get("confidence", ""),
        "topic_match": judgment.get("topic_match", ""),
        "deliverable_match": judgment.get("deliverable_match", ""),
        "requirement_coverage": judgment.get("requirement_coverage", ""),
        "context_fit": judgment.get("context_fit", ""),
        "reason": judgment.get("reason", ""),
        "verifier_relevance": verification.get("relevance", ""),
        "verifier_confidence": verification.get("confidence", ""),
        "verifier_agrees": verification.get("agrees", ""),
    }


def _resolve_judgments(
    pairs: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results_by_id = {str(row.get("judgment_id") or ""): row for row in results}
    missing_ids = [pair["judgment_id"] for pair in pairs if pair["judgment_id"] not in results_by_id]
    if missing_ids:
        raise LLMResponseError(f"LLM response missing judgments: {_format_missing_ids(missing_ids)}")
    resolved = []
    for pair in pairs:
        judgment_id = pair["judgment_id"]
        result = results_by_id[judgment_id]
        resolved.append(
            {
                **_normalize_judgment(result),
                "judgment_id": judgment_id,
                "section": pair["section"],
                "chunk_id": pair["chunk_id"],
                "mdl_doc_id": pair["mdl"]["doc_id"],
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


def _pool_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row["section"]), str(row["chunk_id"]))


def _normalize_judgment(judgment: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(judgment)
    for field in ("topic_match", "deliverable_match", "requirement_coverage", "context_fit", "relevance"):
        if field in normalized:
            normalized[field] = _clamp_int(normalized[field], 0, 3)
    normalized["confidence"] = _clamp_float(normalized.get("confidence"), 0.0, 1.0)
    return normalized


def _normalize_verification(verification: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(verification)
    if normalized.get("relevance") != "":
        normalized["relevance"] = _clamp_int(normalized.get("relevance"), 0, 3)
    normalized["confidence"] = _clamp_float(normalized.get("confidence"), 0.0, 1.0)
    normalized["agrees"] = normalized.get("agrees") is True
    return normalized


def _stable_seed(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _plural(items: list[Any]) -> str:
    return "" if len(items) == 1 else "s"
