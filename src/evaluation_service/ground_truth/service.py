"""Build LLM-assisted ground truth for ITB to MDL matching."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from common.json_io import read_json, write_json
from common.llm_json import parse_json_output
from schedule_service.normalizer import normalize_equipment

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_JUDGE_PROMPT_PATH = PROMPTS_DIR / "matching_relevance_judge.md"
DEFAULT_POSITIVE_JUDGE_PROMPT_PATH = PROMPTS_DIR / "matching_positive_judge.md"
DEFAULT_VERIFY_PROMPT_PATH = PROMPTS_DIR / "matching_relevance_verify.md"
DEFAULT_AUDIT_PROMPT_PATH = PROMPTS_DIR / "matching_ground_truth_audit.md"
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
AUDIT_HEADER = [
    "section",
    "chunk_id",
    "mdl_doc_id",
    "judgment_id",
    "audit_status",
    "audit_relevance",
    "reason",
]
AUDIT_REVIEW_HEADER = [
    *HIGH_PRECISION_HEADER,
    "audit_status",
    "audit_relevance",
    "audit_reason",
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
    max_itb_chunks: int = 0
    equipment_types: tuple[str, ...] = ()
    verify: bool = True
    positive_only: bool = True
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

    def build_pool(self, extract_dir: Path, matching_dir: Path, pool_path: Path | None = None) -> list[dict[str, Any]]:
        """Build a candidate pool from existing matching artifacts."""
        itb_rows = limit_itb_rows(load_itb_rows(extract_dir, self.config.sections), self.config.max_itb_chunks)
        matching_records = load_matching_records(matching_dir, self.config.sections, self.config.modes)
        pools = build_candidate_pool(
            itb_rows, matching_records, self.config.pool_top_k, self.config.equipment_types
        )
        if pool_path is not None:
            write_json(pool_path, pools)
        logger.info(
            "{} {} ITB candidate pools with {} MDL candidates{}",
            "Saved" if pool_path is not None else "Built",
            len(pools),
            _candidate_count(pools),
            f": {pool_path}" if pool_path is not None else "",
        )
        return pools

    def judge_to_files(
        self,
        pools: list[dict[str, Any]],
        resume_state_path: Path | None,
        ground_truth_path: Path | None,
        positive_path: Path | None = None,
        negative_path: Path | None = None,
        verified_path: Path | None = None,
    ) -> None:
        """Generate judgments, optionally verify rows, and write ground truth."""
        output_judgments, verifications = self.judge(pools, resume_state_path)
        if ground_truth_path is not None:
            write_ground_truth(ground_truth_path, output_judgments, verifications)
            logger.info("Saved silver ground truth: {}", ground_truth_path)
        if positive_path is not None and negative_path is not None:
            write_high_precision_ground_truth(
                positive_path,
                negative_path,
                output_judgments,
                verifications,
                verified_path,
            )

    def judge(
        self,
        pools: list[dict[str, Any]],
        resume_state_path: Path | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Generate judgments and optional verifications without writing output CSV files."""
        pairs = iter_judge_pairs(pools)
        pair_ids = {pair["judgment_id"] for pair in pairs}
        if self.config.resume:
            if resume_state_path is None:
                raise ValueError("resume_state_path is required when resume is enabled")
            judgments, verifications = read_resume_state(resume_state_path, pair_ids)
        else:
            judgments = []
            verifications = []
        if self.config.positive_only:
            judgments = self._select_positive_pools(pools, pairs, judgments, verifications, resume_state_path)
        else:
            judgments = self._judge_pools(pools, pairs, judgments, verifications, resume_state_path)
        if self.config.verify:
            verifications = self._verify_judgments(pairs, judgments, verifications, resume_state_path)
        output_judgments = _positive_judgments(judgments) if self.config.positive_only else judgments
        return output_judgments, verifications

    def _judge_pools(
        self,
        pools: list[dict[str, Any]],
        pairs: list[dict[str, Any]],
        judgments: list[dict[str, Any]],
        verifications: list[dict[str, Any]],
        resume_state_path: Path | None,
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
            "Ground truth judge will process {} candidates across {} ITB pools "
            "({} already completed, max {} candidates per call, concurrency {})",
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
            if resume_state_path is not None:
                write_resume_state(resume_state_path, judgments, verifications)
            self.sleep(self.config.batch_delay_seconds)
        logger.info("Completed {} relevance judgments", len(judgments))
        return judgments

    def _select_positive_pools(
        self,
        pools: list[dict[str, Any]],
        pairs: list[dict[str, Any]],
        judgments: list[dict[str, Any]],
        verifications: list[dict[str, Any]],
        resume_state_path: Path | None,
    ) -> list[dict[str, Any]]:
        completed_pool_keys = read_positive_completed_pool_keys(resume_state_path) if resume_state_path else set()
        completed_judgment_ids = {row.get("judgment_id") for row in _positive_judgments(judgments)}
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
                    positive_only_completed_pools=completed_pool_keys,
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
        resume_state_path: Path | None,
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
            if resume_state_path is not None:
                write_resume_state(resume_state_path, judgments, verifications)
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


@dataclass(frozen=True)
class AuditConfig:
    """Runtime settings for auditing final matching ground truth."""

    model: str
    sections: tuple[str, ...] = ("6", "7")
    batch_size: int = 5
    llm_retries: int = 2
    max_concurrency: int = 1
    max_rows: int = 0
    node_label: str = "TestMDLDocument"
    batch_delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model is required")
        if not self.sections:
            raise ValueError("at least one section is required")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.llm_retries < 0:
            raise ValueError("llm_retries cannot be negative")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if self.max_rows < 0:
            raise ValueError("max_rows cannot be negative")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.node_label):
            raise ValueError(f"Invalid Neo4j identifier: {self.node_label}")
        if self.batch_delay_seconds < 0:
            raise ValueError("batch_delay_seconds cannot be negative")


@dataclass(frozen=True)
class _AuditTask:
    order: int
    batch_index: int
    batch_count: int
    payloads: list[dict[str, Any]]


class GroundTruthAuditService:
    """Audit final positive ground-truth rows with an LLM."""

    def __init__(
        self,
        config: AuditConfig,
        client: Any,
        repository: Any,
        audit_prompt: str,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.client = client
        self.repository = repository
        self.audit_prompt = audit_prompt
        self.sleep = sleep

    def audit_to_file(
        self,
        ground_truth_path: Path,
        extract_dir: Path,
        output_path: Path,
        audited_ground_truth_path: Path | None = None,
        suspicious_path: Path | None = None,
    ) -> None:
        """Audit final ground-truth rows and write audit and optional filtered CSVs."""
        rows = load_positive_ground_truth_rows((ground_truth_path,))
        rows = [
            row
            for row in rows
            if str(row.get("section") or "").strip() in self.config.sections
        ]
        if self.config.max_rows:
            rows = rows[: self.config.max_rows]
        itb_rows = load_itb_rows(extract_dir, self.config.sections)
        mdl_docs = self.repository.load_by_doc_ids(_ground_truth_doc_ids(rows))
        payloads, unresolved_rows = build_audit_payloads(rows, itb_rows, mdl_docs)
        audit_rows = [
            {
                "section": row["section"],
                "chunk_id": row["chunk_id"],
                "mdl_doc_id": row["mdl_doc_id"],
                "judgment_id": f"{row['section']}:{row['chunk_id']}:{row['mdl_doc_id']}",
                "audit_status": "unresolved",
                "audit_relevance": "",
                "reason": "Could not resolve ITB or MDL content from the supplied artifacts.",
            }
            for row in unresolved_rows
        ]
        logger.info(
            "Ground truth audit will process {} rows with LLM and {} unresolved rows",
            len(payloads),
            len(unresolved_rows),
        )
        audit_rows.extend(self._audit_payloads(payloads))
        audit_rows = sorted(audit_rows, key=_audit_row_sort_key)
        _write_csv(output_path, AUDIT_HEADER, audit_rows)
        logger.info("Saved ground-truth audit report: {}", output_path)
        if audited_ground_truth_path is not None or suspicious_path is not None:
            audited_rows, suspicious_rows = build_audited_ground_truth_rows(rows, audit_rows)
            if audited_ground_truth_path is not None:
                _write_high_precision_rows(audited_ground_truth_path, audited_rows)
                logger.info("Saved {} audited ground-truth rows: {}", len(audited_rows), audited_ground_truth_path)
            if suspicious_path is not None:
                _write_csv(suspicious_path, AUDIT_REVIEW_HEADER, suspicious_rows)
                logger.info(
                    "Saved {} suspicious ground-truth rows for review: {}",
                    len(suspicious_rows),
                    suspicious_path,
                )

    def _audit_payloads(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tasks = [
            _AuditTask(index, index, len(_chunked(payloads, self.config.batch_size)), payloads_chunk)
            for index, payloads_chunk in enumerate(_chunked(payloads, self.config.batch_size), start=1)
        ]
        rows = []
        for _order, resolved in self._run_audit_tasks(tasks):
            rows.extend(resolved)
        return rows

    def _run_audit_tasks(self, tasks: list[_AuditTask]) -> Iterator[tuple[int, list[dict[str, Any]]]]:
        if self.config.max_concurrency == 1:
            for task in tasks:
                yield task.order, self._run_audit_task(task)
                self.sleep(self.config.batch_delay_seconds)
            return

        with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as executor:
            futures = {executor.submit(self._run_audit_task, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                yield task.order, future.result()

    def _run_audit_task(self, task: _AuditTask) -> list[dict[str, Any]]:
        logger.info(
            "Auditing ground-truth batch {}/{} ({} row{})",
            task.batch_index,
            task.batch_count,
            len(task.payloads),
            _plural(task.payloads),
        )
        return _run_with_retries(
            lambda: _resolve_audit_rows(
                task.payloads,
                _run_llm_batch(self.client, self.config.model, self.audit_prompt, "ground_truth_rows", task.payloads),
            ),
            retries=self.config.llm_retries,
            sleep=self.sleep,
            delay_seconds=self.config.batch_delay_seconds,
            description=f"audit batch {task.batch_index}/{task.batch_count}",
        )


class MDLGroundTruthRepository:
    """Load MDL document context from Neo4j for ground-truth auditing."""

    def __init__(self, conn: Any, node_label: str = "TestMDLDocument") -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node_label):
            raise ValueError(f"Invalid Neo4j identifier: {node_label}")
        self.conn = conn
        self.node_label = node_label

    def load_by_doc_ids(self, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Load MDL documents keyed by doc_id."""
        if not doc_ids:
            return {}
        with self.conn.session() as session:
            records = session.run(
                f"""
                MATCH (n:{self.node_label})
                WHERE n.doc_id IN $doc_ids
                RETURN n.doc_id AS doc_id,
                       n.source_file AS source_file,
                       n.document_no AS document_no,
                       n.title AS title,
                       n.system AS system,
                       n.equipment AS equipment,
                       n.building AS building,
                       n.study_survey AS study_survey,
                       n.others AS others,
                       n.deliverable AS deliverable,
                       n.text_content AS text_content
                """,
                doc_ids=doc_ids,
            )
            return {str(record["doc_id"]): dict(record) for record in records}


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
    equipment_types: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Merge and deduplicate top MDL candidates from each retrieval mode.

    When ``equipment_types`` is non-empty, only candidates whose normalized
    ``equipment`` matches one of those canonical names are kept — chunks left
    with no matching candidates are dropped from the pool entirely.
    """
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
            for candidate in record.get("candidates", [])[:top_k]:
                if not _equipment_matches(candidate.get("equipment", ""), equipment_types):
                    continue
                candidate_key = _candidate_key(candidate)
                if not candidate_key:
                    continue
                candidates_by_id.setdefault(candidate_key, _build_pool_candidate(candidate))
            pool["_candidates_by_id"] = candidates_by_id

    pools = []
    for key in sorted(pools_by_key):
        pool = pools_by_key[key]
        candidates = list(pool.pop("_candidates_by_id").values())
        if not candidates:
            continue
        random.Random(_stable_seed(key)).shuffle(candidates)
        pool["candidates"] = candidates
        pools.append(pool)
    return pools


def build_audit_payloads(
    ground_truth_rows: list[dict[str, Any]],
    itb_rows: dict[str, dict[str, Any]],
    mdl_docs: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build LLM audit payloads from final ground-truth rows."""
    payloads = []
    unresolved_rows = []
    for row in ground_truth_rows:
        section = str(row.get("section") or "").strip()
        chunk_id = str(row.get("chunk_id") or "").strip()
        doc_id = str(row.get("mdl_doc_id") or "").strip()
        itb = itb_rows.get(f"{section}:{chunk_id}")
        mdl = mdl_docs.get(doc_id)
        if not section or not chunk_id or not doc_id or itb is None or mdl is None:
            unresolved_rows.append(row)
            continue
        payloads.append(
            {
                "judgment_id": f"{section}:{chunk_id}:{doc_id}",
                "section": section,
                "chunk_id": chunk_id,
                "mdl_doc_id": doc_id,
                "itb": _build_audit_itb(section, chunk_id, itb),
                "mdl": {field: mdl.get(field, "") for field in MDL_CANDIDATE_FIELDS},
                "current_label": {
                    "relevance": row.get("relevance", ""),
                    "final_relevance": row.get("final_relevance", ""),
                    "label_status": row.get("label_status", ""),
                },
            }
        )
    return payloads, unresolved_rows


def build_audited_ground_truth_rows(
    ground_truth_rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split audited ground truth into kept ok rows and suspicious review rows."""
    audit_by_key = {
        _ground_truth_row_key(row): row
        for row in audit_rows
    }
    ok_rows = []
    suspicious_rows = []
    for row in ground_truth_rows:
        audit = audit_by_key.get(_ground_truth_row_key(row), {})
        status = str(audit.get("audit_status") or "").strip().lower()
        if status == "ok":
            ok_rows.append({field: row.get(field, "") for field in HIGH_PRECISION_HEADER})
        elif status == "suspicious":
            suspicious_rows.append(
                {
                    **{field: row.get(field, "") for field in HIGH_PRECISION_HEADER},
                    "audit_status": status,
                    "audit_relevance": audit.get("audit_relevance", ""),
                    "audit_reason": audit.get("reason", ""),
                }
            )
    return _dedupe_ground_truth_rows(ok_rows), suspicious_rows


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
                        for field in MDL_CANDIDATE_FIELDS
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


def read_resume_state(resume_state_path: Path, pair_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not resume_state_path.exists():
        return [], []
    state = read_json(resume_state_path)
    judgments = [
        row
        for row in state.get("judgments", [])
        if row.get("judgment_id") in pair_ids
    ]
    verifications = [
        row
        for row in state.get("verifications", [])
        if row.get("judgment_id") in pair_ids
    ]
    return judgments, verifications


def read_positive_completed_pool_keys(resume_state_path: Path) -> set[tuple[str, str]]:
    if not resume_state_path.exists():
        return set()
    state = read_json(resume_state_path)
    return {
        (str(row.get("section")), str(row.get("chunk_id")))
        for row in state.get("positive_only_completed_pools", [])
        if row.get("section") and row.get("chunk_id")
    }


def write_resume_state(
    resume_state_path: Path,
    judgments: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
    positive_only_completed_pools: set[tuple[str, str]] | None = None,
) -> None:
    state = {
        "summary": {
            "judgment_count": len(judgments),
            "verification_count": len(verifications),
        },
        "judgments": judgments,
        "verifications": verifications,
    }
    if positive_only_completed_pools is not None:
        state["positive_only_completed_pools"] = [
            {"section": section, "chunk_id": chunk_id}
            for section, chunk_id in sorted(positive_only_completed_pools)
        ]
    write_json(resume_state_path, state)


def write_high_precision_ground_truth(
    positive_path: Path,
    negative_path: Path,
    judgments: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
    verified_path: Path | None = None,
) -> None:
    """Write clear positive and negative labels agreed by judge and verifier."""
    verified_rows = build_high_precision_ground_truth_rows(judgments, verifications)
    rows_by_status = {
        "positive": [row for row in verified_rows if row["label_status"] == "positive"],
        "negative": [row for row in verified_rows if row["label_status"] == "negative"],
    }
    rows_by_status["positive"] = _dedupe_ground_truth_rows(rows_by_status["positive"])
    rows_by_status["negative"] = _dedupe_ground_truth_rows(rows_by_status["negative"])
    verified_rows = _dedupe_ground_truth_rows(verified_rows)
    _write_high_precision_rows(positive_path, rows_by_status["positive"])
    _write_high_precision_rows(negative_path, rows_by_status["negative"])
    if verified_path is not None:
        _write_high_precision_rows(verified_path, verified_rows)
    logger.info(
        "Saved {} positive and {} negative high-precision ground truth labels: {}, {}{}",
        len(rows_by_status["positive"]),
        len(rows_by_status["negative"]),
        positive_path,
        negative_path,
        f", {verified_path}" if verified_path is not None else "",
    )


def build_high_precision_ground_truth_rows(
    judgments: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build clear positive and negative labels agreed by judge and verifier."""
    verification_by_id = {row.get("judgment_id"): row for row in verifications}
    rows = []
    for judgment in judgments:
        verification = verification_by_id.get(judgment.get("judgment_id"), {})
        label_status = _high_precision_label_status(judgment, verification)
        if not label_status:
            continue
        row = _build_ground_truth_row(judgment, verification)
        rows.append(
            {
                **row,
                "final_relevance": int(verification["relevance"]),
                "label_status": label_status,
            }
        )
    return _dedupe_ground_truth_rows(rows)


def build_verified_positive_ground_truth_rows(
    judgments: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build verified positive rows for the canonical ground-truth file."""
    return [
        row
        for row in build_high_precision_ground_truth_rows(judgments, verifications)
        if row["label_status"] == "positive"
    ]


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


def _resolve_audit_rows(payloads: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload_by_id = {payload["judgment_id"]: payload for payload in payloads}
    result_by_id = {}
    for result in results:
        judgment_id = str(result.get("judgment_id") or "").strip()
        if judgment_id in payload_by_id and judgment_id not in result_by_id:
            result_by_id[judgment_id] = result
    missing_ids = [payload["judgment_id"] for payload in payloads if payload["judgment_id"] not in result_by_id]
    if missing_ids:
        raise LLMResponseError(f"LLM response missing audit rows: {', '.join(missing_ids)}")
    return [
        _normalize_audit_row(payload_by_id[judgment_id], result_by_id[judgment_id])
        for judgment_id in payload_by_id
    ]


def _normalize_audit_row(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("audit_status") or "").strip().lower()
    if status not in {"ok", "suspicious", "remove"}:
        status = "suspicious"
    return {
        "section": payload["section"],
        "chunk_id": payload["chunk_id"],
        "mdl_doc_id": payload["mdl_doc_id"],
        "judgment_id": payload["judgment_id"],
        "audit_status": status,
        "audit_relevance": _clamp_int(result.get("audit_relevance", 0), 0, 3),
        "reason": str(result.get("reason") or "").strip(),
    }


def _max_completion_tokens(payloads: list[dict[str, Any]]) -> int:
    result_count = sum(len(payload.get("candidates", [])) or 1 for payload in payloads)
    return min(8192, 1024 * result_count)


def _candidate_count(pools: list[dict[str, Any]]) -> int:
    return sum(len(pool.get("candidates", [])) for pool in pools)


def _ground_truth_doc_ids(rows: list[dict[str, Any]]) -> list[str]:
    doc_ids = []
    seen = set()
    for row in rows:
        doc_id = str(row.get("mdl_doc_id") or "").strip()
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            doc_ids.append(doc_id)
    return doc_ids


def _build_audit_itb(section: str, chunk_id: str, itb_row: dict[str, Any]) -> dict[str, Any]:
    text = itb_row.get("Chunk Text", "")
    return {
        "document": itb_row.get("Document", ""),
        "chunk_id": chunk_id,
        "page": itb_row.get("Page", ""),
        "section": itb_row.get("Section", section),
        "hierarchy_context": itb_row.get("Hierarchy Context", ""),
        "depths": _build_itb_depths(itb_row, {}),
        "keywords": itb_row.get("Keywords", ""),
        "text": text,
        "chunk_text": text,
    }


def _write_csv(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _audit_row_sort_key(row: dict[str, Any]) -> tuple[tuple[int, int | str], str, str]:
    return (
        _section_sort_key(str(row.get("section") or "")),
        str(row.get("chunk_id") or ""),
        str(row.get("mdl_doc_id") or ""),
    )


def _section_sort_key(section: str) -> tuple[int, int | str]:
    return (0, int(section)) if section.isdigit() else (1, section)


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


def _equipment_matches(raw_equipment: Any, equipment_types: tuple[str, ...]) -> bool:
    """Check a candidate's equipment against an allow-list of canonical names.

    An empty ``equipment_types`` means no filtering (everything matches). Raw
    values are normalized first since source MDLs store equipment inconsistently
    (e.g. "Air Cooled Condenser" vs "AIR COOLED CONDENSER" vs "ACC").
    """
    if not equipment_types:
        return True
    normalized = normalize_equipment(str(raw_equipment or "").strip())
    return normalized in equipment_types


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


def _high_precision_label_status(judgment: dict[str, Any], verification: dict[str, Any]) -> str:
    if not verification.get("agrees"):
        return ""
    judge_relevance = _clamp_int(judgment.get("relevance"), 0, 3)
    verifier_relevance = _clamp_int(verification.get("relevance"), 0, 3)
    if judge_relevance != verifier_relevance:
        return ""
    return "positive" if verifier_relevance == 3 else "negative"


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


def _positive_judgments(judgments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [judgment for judgment in judgments if _clamp_int(judgment.get("relevance"), 0, 3) == 3]


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


def _judgment_pool_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("section", "")), str(row.get("chunk_id", "")))


def _normalize_judgment(judgment: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(judgment)
    normalized.pop("confidence", None)
    for field in ("topic_match", "deliverable_match", "requirement_coverage", "context_fit", "relevance"):
        if field in normalized:
            normalized[field] = _clamp_int(normalized[field], 0, 3)
    return normalized


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
