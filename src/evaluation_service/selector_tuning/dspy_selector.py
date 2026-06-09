"""Generic DSPy-based tuning and inference for final document selectors."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from common.config import azure_endpoint, load_env_file, required_env

DEFAULT_DSPY_CHAT_API_VERSION = "2024-12-01-preview"
DEFAULT_PROGRAM_FILENAME = "selector_program.json"
DEFAULT_TASK_RULES = (
    "Select only the exact matching document IDs from the supplied candidate list. "
    "Never invent IDs. Return an empty list when no candidate clearly matches."
)


@dataclass(frozen=True)
class SelectorExample:
    """One supervised selector example."""

    project_name: str
    itb_scope: str
    chunk_id: str
    chunk_json: str
    candidate_json: str
    candidate_doc_ids: tuple[str, ...]
    selected_doc_ids: tuple[str, ...]

    @property
    def is_positive(self) -> bool:
        return bool(self.selected_doc_ids)


@dataclass(frozen=True)
class SelectorTuneConfig:
    """GEPA selector compile settings."""

    model: str
    reflection_model: str | None = None
    auto: str | None = "medium"
    api_version_env: str = "AZURE_OPENAI_CHAT_API_VERSION"
    default_api_version: str = DEFAULT_DSPY_CHAT_API_VERSION
    cache: bool = False
    num_threads: int | None = None
    max_metric_calls: int | None = None
    max_full_evals: int | None = None
    reflection_minibatch_size: int = 3
    seed: int = 7
    use_merge: bool = True
    track_stats: bool = False
    verbose_dspy: bool = False

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model is required")
        if self.reflection_model is not None and not self.reflection_model:
            raise ValueError("reflection_model cannot be empty when provided")
        if self.auto is not None and self.auto not in {"light", "medium", "heavy"}:
            raise ValueError("auto must be light, medium, or heavy")
        if self.num_threads is not None and self.num_threads <= 0:
            raise ValueError("num_threads must be positive when provided")
        if self.max_metric_calls is not None and self.max_metric_calls <= 0:
            raise ValueError("max_metric_calls must be positive when provided")
        if self.max_full_evals is not None and self.max_full_evals <= 0:
            raise ValueError("max_full_evals must be positive when provided")
        if self.reflection_minibatch_size <= 0:
            raise ValueError("reflection_minibatch_size must be positive")
        budget_count = sum(value is not None for value in (self.auto, self.max_metric_calls, self.max_full_evals))
        if budget_count != 1:
            raise ValueError("Exactly one of auto, max_metric_calls, or max_full_evals must be set for GEPA")


class DSPySelectorPredictor:
    """Load and run a compiled DSPy selector program."""

    def __init__(
        self,
        *,
        program_path: Path,
        model: str,
        expected_instruction: str = "",
        api_version_env: str = "AZURE_OPENAI_CHAT_API_VERSION",
        default_api_version: str = DEFAULT_DSPY_CHAT_API_VERSION,
    ) -> None:
        if not program_path.exists():
            raise FileNotFoundError(f"Missing DSPy selector program: {program_path}")
        self._dspy = _require_dspy()
        lm = _build_dspy_lm(
            self._dspy,
            model=model,
            api_version_env=api_version_env,
            default_api_version=default_api_version,
            cache=False,
        )
        self._dspy.configure(lm=lm, track_usage=True)
        instruction_text = expected_instruction or DEFAULT_TASK_RULES
        self._program = _build_selector_program(self._dspy, instruction_text)
        self._program.load(str(program_path))
        self.program_path = program_path

    def select(self, record: dict[str, Any]) -> dict[str, Any]:
        candidate_payload = [_build_candidate_payload(candidate) for candidate in record["candidates"]]
        prediction = self._program(
            project_name=record["project_name"],
            itb_scope=record["itb_scope"],
            chunk_id=record["chunk_id"],
            chunk_json=json.dumps(record["itb"], ensure_ascii=False),
            candidate_json=json.dumps(candidate_payload, ensure_ascii=False),
        )
        selected_doc_ids = _normalize_doc_ids(
            getattr(prediction, "selected_doc_ids", []),
            {candidate["doc_id"] for candidate in record["candidates"]},
        )
        usage = _flatten_dspy_usage(prediction.get_lm_usage() if hasattr(prediction, "get_lm_usage") else {})
        return {
            "chunk_id": record["chunk_id"],
            "selected_doc_ids": selected_doc_ids,
            "_usage": usage,
        }


def compile_selector_program(
    *,
    train_examples: list[SelectorExample],
    dev_examples: list[SelectorExample],
    output_dir: Path,
    config: SelectorTuneConfig,
    instruction_text: str,
) -> dict[str, Any]:
    """Compile and save a DSPy selector program."""
    if not train_examples:
        raise ValueError("train_examples cannot be empty")
    if not dev_examples:
        raise ValueError("dev_examples cannot be empty")

    dspy = _require_dspy()
    logger.info(
        "Starting GEPA selector compile with {} train example(s), {} dev example(s), "
        "task_model={}, reflection_model={}, auto={}, max_metric_calls={}, "
        "max_full_evals={}, reflection_minibatch_size={}, num_threads={}",
        len(train_examples),
        len(dev_examples),
        config.model,
        config.reflection_model or config.model,
        config.auto,
        config.max_metric_calls,
        config.max_full_evals,
        config.reflection_minibatch_size,
        config.num_threads,
    )
    task_lm = _build_dspy_lm(
        dspy,
        model=config.model,
        api_version_env=config.api_version_env,
        default_api_version=config.default_api_version,
        cache=config.cache,
    )
    reflection_lm = _build_dspy_lm(
        dspy,
        model=config.reflection_model or config.model,
        api_version_env=config.api_version_env,
        default_api_version=config.default_api_version,
        cache=config.cache,
    )
    dspy.configure(lm=task_lm, track_usage=False)

    optimizer = _build_optimizer(dspy, reflection_lm, config)
    trainset = [_to_dspy_example(dspy, example) for example in train_examples]
    devset = [_to_dspy_example(dspy, example) for example in dev_examples]
    with _dspy_runtime_logging(config.verbose_dspy):
        compiled = optimizer.compile(_build_selector_program(dspy, instruction_text), trainset=trainset, valset=devset)

    output_dir.mkdir(parents=True, exist_ok=True)
    program_path = output_dir / DEFAULT_PROGRAM_FILENAME
    compiled.save(str(program_path))

    with _dspy_runtime_logging(config.verbose_dspy):
        dev_metrics = evaluate_selector_program(compiled, dev_examples)
    logger.info(
        "Finished GEPA selector compile. Dev precision={:.4f}, recall={:.4f}, f1={:.4f}",
        dev_metrics["avg_precision"],
        dev_metrics["avg_recall"],
        dev_metrics["avg_f1"],
    )
    return {
        "program_path": program_path,
        "framework": "dspy_selector",
        "optimizer": "gepa",
        "auto": config.auto,
        "metric": "f1",
        "model": config.model,
        "reflection_model": config.reflection_model or config.model,
        "train_examples": len(train_examples),
        "dev_examples": len(dev_examples),
        "positive_train_examples": sum(example.is_positive for example in train_examples),
        "positive_dev_examples": sum(example.is_positive for example in dev_examples),
        "task_rules_sha256": _sha256_text(instruction_text),
        "created_at": datetime.now(UTC).isoformat(),
        "dev_metrics": dev_metrics,
    }


def evaluate_selector_program(program: Any, examples: list[SelectorExample]) -> dict[str, float | int]:
    """Evaluate a selector program on examples with set-level F1 metrics."""
    if not examples:
        return {"queries": 0, "positive_queries": 0, "avg_precision": 0.0, "avg_recall": 0.0, "avg_f1": 0.0}

    precision_scores = []
    recall_scores = []
    f1_scores = []
    for example in examples:
        prediction = program(
            project_name=example.project_name,
            itb_scope=example.itb_scope,
            chunk_id=example.chunk_id,
            chunk_json=example.chunk_json,
            candidate_json=example.candidate_json,
        )
        predicted_ids = _normalize_doc_ids(getattr(prediction, "selected_doc_ids", []), set(example.candidate_doc_ids))
        precision, recall, f1 = _positive_precision_recall_f1(set(example.selected_doc_ids), set(predicted_ids))
        precision_scores.append(precision)
        recall_scores.append(recall)
        f1_scores.append(f1)

    return {
        "queries": len(examples),
        "positive_queries": sum(example.is_positive for example in examples),
        "avg_precision": sum(precision_scores) / len(precision_scores),
        "avg_recall": sum(recall_scores) / len(recall_scores),
        "avg_f1": sum(f1_scores) / len(f1_scores),
    }


def split_selector_examples(
    examples: list[SelectorExample],
    *,
    dev_fraction: float = 0.2,
    seed: int = 7,
) -> tuple[list[SelectorExample], list[SelectorExample]]:
    """Split positive examples into train/dev while preserving scope coverage."""
    if not 0 < dev_fraction < 1:
        raise ValueError("dev_fraction must be between 0 and 1")
    if len(examples) < 2:
        raise ValueError("Need at least 2 examples to split train/dev")

    rng = random.Random(seed)
    positives = [example for example in examples if example.is_positive]
    if len(positives) < 2:
        raise ValueError("Need at least 2 positive examples to tune against F1")

    grouped: dict[str, list[SelectorExample]] = {}
    for example in positives:
        grouped.setdefault(example.itb_scope, []).append(example)

    dev: list[SelectorExample] = []
    train: list[SelectorExample] = []
    for scope in sorted(grouped):
        group = list(grouped[scope])
        rng.shuffle(group)
        dev_slice = _take_dev_slice(group, dev_fraction)
        dev_keys = {(example.itb_scope, example.chunk_id) for example in dev_slice}
        dev.extend(dev_slice)
        train.extend(example for example in group if (example.itb_scope, example.chunk_id) not in dev_keys)

    if not dev:
        shuffled = list(positives)
        rng.shuffle(shuffled)
        dev = [shuffled[0]]
        dev_keys = {(dev[0].itb_scope, dev[0].chunk_id)}
        train = [example for example in positives if (example.itb_scope, example.chunk_id) not in dev_keys]

    if not train or not dev:
        raise ValueError("Train/dev split produced an empty partition; adjust data or dev_fraction")
    logger.info(
        "Split selector examples into {} train / {} dev examples across {} scope(s)",
        len(train),
        len(dev),
        len({example.itb_scope for example in examples}),
    )
    return train, dev


class _SelectorSignatureProxy:
    """Small namespace to hold the generic selector signature builder."""

    @staticmethod
    def build(dspy: Any, instruction_text: str) -> type:
        class SelectorSignature(dspy.Signature):
            """Temporary selector signature docstring."""

            project_name: str = dspy.InputField(desc="Project or experiment name.")
            itb_scope: str = dspy.InputField(desc="ITB document scope.")
            chunk_id: str = dspy.InputField(desc="ITB chunk identifier.")
            chunk_json: str = dspy.InputField(desc="JSON object describing the ITB chunk.")
            candidate_json: str = dspy.InputField(
                desc="JSON array of candidate documents. Only these doc_ids may be selected."
            )
            selected_doc_ids: list[str] = dspy.OutputField(
                desc="Exact doc_id values from candidate_json that clearly match the chunk."
            )

        SelectorSignature.__doc__ = instruction_text
        return SelectorSignature


def _build_selector_program(dspy: Any, instruction_text: str) -> Any:
    signature = _SelectorSignatureProxy.build(dspy, instruction_text)

    class SelectorProgram(dspy.Module):
        def __init__(self) -> None:
            super().__init__()
            self.selector = dspy.Predict(signature)

        def forward(
            self,
            *,
            project_name: str,
            itb_scope: str,
            chunk_id: str,
            chunk_json: str,
            candidate_json: str,
        ) -> Any:
            return self.selector(
                project_name=project_name,
                itb_scope=itb_scope,
                chunk_id=chunk_id,
                chunk_json=chunk_json,
                candidate_json=candidate_json,
            )

    return SelectorProgram()


def _require_dspy() -> Any:
    try:
        import dspy
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError("DSPy is required for selector tuning. Install the 'dspy' package first.") from exc
    return dspy


@contextmanager
def _dspy_runtime_logging(verbose_dspy: bool):
    if verbose_dspy:
        yield
        return

    logger_names = [
        "dspy",
        "dspy.evaluate",
        "dspy.evaluate.evaluate",
        "dspy.teleprompt",
        "dspy.teleprompt.gepa",
        "dspy.teleprompt.gepa.gepa",
        "gepa",
    ]
    previous_levels = {name: logging.getLogger(name).level for name in logger_names}
    for name in logger_names:
        logging.getLogger(name).setLevel(logging.WARNING)

    original_optimize = None
    try:
        import gepa
    except ImportError:  # pragma: no cover - depends on environment
        gepa = None

    if gepa is not None:
        original_optimize = gepa.optimize

        def quiet_optimize(*args: Any, **kwargs: Any):
            kwargs["display_progress_bar"] = False
            return original_optimize(*args, **kwargs)

        gepa.optimize = quiet_optimize

    try:
        yield
    finally:
        for name, level in previous_levels.items():
            logging.getLogger(name).setLevel(level)
        if gepa is not None and original_optimize is not None:
            gepa.optimize = original_optimize


def _build_dspy_lm(dspy: Any, *, model: str, api_version_env: str, default_api_version: str, cache: bool) -> Any:
    load_env_file()
    return dspy.LM(
        f"azure/{model}",
        api_key=required_env("AZURE_OPENAI_API_KEY"),
        api_base=azure_endpoint(),
        api_version=os.getenv(api_version_env, default_api_version),
        cache=cache,
        temperature=0.0,
        max_tokens=4096,
    )


def _build_optimizer(dspy: Any, lm: Any, config: SelectorTuneConfig) -> Any:
    return dspy.GEPA(
        metric=lambda example, prediction, trace=None, pred_name=None, pred_trace=None: _selector_gepa_metric(
            dspy,
            example,
            prediction,
            trace=trace,
            pred_name=pred_name,
            pred_trace=pred_trace,
        ),
        auto=config.auto,
        reflection_lm=lm,
        reflection_minibatch_size=config.reflection_minibatch_size,
        max_metric_calls=config.max_metric_calls,
        max_full_evals=config.max_full_evals,
        num_threads=config.num_threads,
        use_merge=config.use_merge,
        seed=config.seed,
        track_stats=config.track_stats,
    )


def _to_dspy_example(dspy: Any, example: SelectorExample) -> Any:
    return dspy.Example(
        project_name=example.project_name,
        itb_scope=example.itb_scope,
        chunk_id=example.chunk_id,
        chunk_json=example.chunk_json,
        candidate_json=example.candidate_json,
        selected_doc_ids=list(example.selected_doc_ids),
        candidate_doc_ids=list(example.candidate_doc_ids),
    ).with_inputs("project_name", "itb_scope", "chunk_id", "chunk_json", "candidate_json")


def _selector_gepa_metric(
    dspy: Any,
    example: Any,
    prediction: Any,
    *,
    trace: Any = None,
    pred_name: str | None = None,
    pred_trace: Any = None,
) -> Any:
    del trace, pred_trace
    candidate_ids = {str(doc_id).strip() for doc_id in getattr(example, "candidate_doc_ids", []) if str(doc_id).strip()}
    truth_ids = {str(doc_id).strip() for doc_id in getattr(example, "selected_doc_ids", []) if str(doc_id).strip()}
    predicted_ids = set(_normalize_doc_ids(getattr(prediction, "selected_doc_ids", []), candidate_ids))
    precision, recall, f1 = _positive_precision_recall_f1(truth_ids, predicted_ids)
    feedback = _build_gepa_feedback(
        example=example,
        truth_ids=truth_ids,
        predicted_ids=predicted_ids,
        precision=precision,
        recall=recall,
        f1=f1,
        pred_name=pred_name,
    )
    return dspy.Prediction(score=f1, feedback=feedback)


def _normalize_doc_ids(selected_doc_ids: Any, candidate_ids: set[str]) -> list[str]:
    if not isinstance(selected_doc_ids, list):
        return []
    normalized = []
    seen = set()
    for doc_id in selected_doc_ids:
        text = str(doc_id).strip()
        if text and text in candidate_ids and text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized


def _positive_precision_recall_f1(truth_ids: set[str], predicted_ids: set[str]) -> tuple[float, float, float]:
    if not truth_ids:
        raise ValueError("Positive-only metric received a no-match example")
    if not predicted_ids:
        return 1.0, 0.0, 0.0
    hit_count = len(truth_ids & predicted_ids)
    precision = hit_count / len(predicted_ids) if predicted_ids else 0.0
    recall = hit_count / len(truth_ids) if truth_ids else 0.0
    if precision + recall == 0:
        return precision, recall, 0.0
    return precision, recall, 2 * precision * recall / (precision + recall)


def _build_candidate_payload(candidate: dict[str, str]) -> dict[str, str]:
    return {
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


def _build_gepa_feedback(
    *,
    example: Any,
    truth_ids: set[str],
    predicted_ids: set[str],
    precision: float,
    recall: float,
    f1: float,
    pred_name: str | None,
) -> str:
    missing_ids = sorted(truth_ids - predicted_ids)
    unexpected_ids = sorted(predicted_ids - truth_ids)
    candidate_map = _candidate_map_from_json(getattr(example, "candidate_json", ""))
    header = (
        f"Selector score summary: precision={precision:.3f}, recall={recall:.3f}, f1={f1:.3f}. "
        f"Target predictor: {pred_name or 'selector'}."
    )
    if not truth_ids:
        return header + " No positive ground truth is available for this tuning example."
    if not predicted_ids:
        return (
            header
            + " The selector missed all correct documents. "
            + "It should become more willing to keep directly matching core requirement-family documents. "
            + "Missing docs: "
            + _describe_doc_ids(missing_ids, candidate_map)
        )

    parts = [header]
    if missing_ids:
        parts.append(
            "Missing docs show where the selector was too strict or failed to keep the core requirement family: "
            + _describe_doc_ids(missing_ids, candidate_map)
        )
        parts.append("Missing-pattern diagnosis: " + _summarize_doc_patterns(missing_ids, candidate_map))
    if unexpected_ids:
        parts.append(
            "Unexpected docs show where the selector was too broad or confused adjacent systems: "
            + _describe_doc_ids(unexpected_ids, candidate_map)
        )
        parts.append("Unexpected-pattern diagnosis: " + _summarize_doc_patterns(unexpected_ids, candidate_map))
    if missing_ids and unexpected_ids:
        parts.append(
            "Improve by keeping only the exact subsystem and purpose, while still selecting the main matching family "
            "such as specification, general arrangement, functional description, logic diagram, "
            "or datasheet when clearly relevant."
        )
    elif missing_ids:
        parts.append(
            "Improve by being less conservative for directly matching core documents in the same subsystem and purpose."
        )
    elif unexpected_ids:
        parts.append(
            "Improve by being stricter about adjacent systems, broad package spillover, "
            "and loosely related support documents."
        )
    return " ".join(parts)


def _candidate_map_from_json(candidate_json: str) -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(candidate_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, list):
        return {}
    mapping = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("doc_id", "")).strip()
        if doc_id:
            mapping[doc_id] = {key: str(value).strip() for key, value in item.items() if value is not None}
    return mapping


def _summarize_doc_patterns(doc_ids: list[str], candidate_map: dict[str, dict[str, str]]) -> str:
    if not doc_ids:
        return "none"
    counts = {
        "adjacent_system": 0,
        "core_requirement_family": 0,
        "broad_layout_or_list": 0,
        "foundation_loading_family": 0,
        "control_logic_family": 0,
    }
    for doc_id in doc_ids:
        candidate = candidate_map.get(doc_id, {})
        text = " ".join(
            [
                candidate.get("title", ""),
                candidate.get("system", ""),
                candidate.get("deliverable", ""),
                candidate.get("others", ""),
            ]
        ).casefold()
        if any(keyword in text for keyword in ("fin fan cooler", "closed cooling water", "condensate", "drain")):
            counts["adjacent_system"] += 1
        if any(
            keyword in text
            for keyword in (
                "general arrangement",
                "functional description",
                "technical specification",
                "specification",
                "datasheet",
            )
        ):
            counts["core_requirement_family"] += 1
        if any(
            keyword in text
            for keyword in (
                "outline drawing",
                "arrangement drawing",
                "support drawing",
                "valve list",
                "terminal point list",
                "pipe line list",
            )
        ):
            counts["broad_layout_or_list"] += 1
        if any(keyword in text for keyword in ("anchorage", "foundation loading")):
            counts["foundation_loading_family"] += 1
        if any(keyword in text for keyword in ("logic diagram", "control logic", "functional description")):
            counts["control_logic_family"] += 1
    ranked = sorted(((count, label) for label, count in counts.items() if count), reverse=True)
    if not ranked:
        return "mixed or uncategorized document family"
    labels = {
        "adjacent_system": "adjacent-system support documents",
        "core_requirement_family": "core requirement-family documents",
        "broad_layout_or_list": "broad layout/list documents",
        "foundation_loading_family": "foundation-loading documents",
        "control_logic_family": "control/logic documents",
    }
    return ", ".join(f"{labels[label]} x{count}" for count, label in ranked[:3])


def _describe_doc_ids(doc_ids: list[str], candidate_map: dict[str, dict[str, str]], limit: int = 8) -> str:
    descriptions = []
    for doc_id in doc_ids[:limit]:
        candidate = candidate_map.get(doc_id, {})
        title = candidate.get("title", "")
        system = candidate.get("system", "")
        deliverable = candidate.get("deliverable", "")
        others = candidate.get("others", "")
        bits = [bit for bit in [title, system, deliverable, others] if bit]
        suffix = f" ({'; '.join(bits)})" if bits else ""
        descriptions.append(f"{doc_id}{suffix}")
    if len(doc_ids) > limit:
        descriptions.append(f"... and {len(doc_ids) - limit} more")
    return "; ".join(descriptions) if descriptions else "none"


def _flatten_dspy_usage(usage: Any) -> dict[str, int]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if not isinstance(usage, dict):
        return totals
    for provider_usage in usage.values():
        if not isinstance(provider_usage, dict):
            continue
        totals["prompt_tokens"] += int(provider_usage.get("prompt_tokens", 0) or 0)
        totals["completion_tokens"] += int(provider_usage.get("completion_tokens", 0) or 0)
        totals["total_tokens"] += int(provider_usage.get("total_tokens", 0) or 0)
    return totals


def _take_dev_slice(examples: list[SelectorExample], dev_fraction: float) -> list[SelectorExample]:
    if not examples:
        return []
    if len(examples) == 1:
        return []
    dev_count = max(1, round(len(examples) * dev_fraction))
    dev_count = min(dev_count, len(examples) - 1)
    return examples[:dev_count]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
