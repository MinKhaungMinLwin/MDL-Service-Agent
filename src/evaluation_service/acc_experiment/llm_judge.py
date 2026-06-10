"""LLM-as-a-judge helpers for ACC experiment business-level evaluation."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from loguru import logger

from common.llm_json import parse_json_output
from common.openai_client import build_azure_openai_client
from common.prompts import load_prompt

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_CHUNK_JUDGE_PROMPT_PATH = PROMPTS_DIR / "itb_chunk_level_judge.md"
DEFAULT_PROJECT_JUDGE_PROMPT_PATH = PROMPTS_DIR / "itb_project_level_judge.md"


def build_llm_judge_client() -> Any:
    """Create the shared Azure OpenAI client for LLM judge scoring."""
    return build_azure_openai_client(
        api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
        default_api_version="2024-12-01-preview",
        timeout=1200.0,
    )


def judge_model_name() -> str:
    """Resolve the Azure deployment to use for LLM judge scoring."""
    return (
        os.getenv("ACC_LLM_JUDGE_MODEL")
        or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
        or ""
    ).strip()


def judge_chunk_level_payload(client: Any, model: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Score one ITB chunk-level selection payload."""
    return _judge_payload(
        client=client,
        model=model,
        prompt=load_prompt(DEFAULT_CHUNK_JUDGE_PROMPT_PATH),
        payload=payload,
        description=f"chunk-level judge {payload.get('itb_scope', '')} {payload.get('chunk_id', '')}".strip(),
    )


def judge_project_level_payload(client: Any, model: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Score one ITB project-level merged payload."""
    return _judge_payload(
        client=client,
        model=model,
        prompt=load_prompt(DEFAULT_PROJECT_JUDGE_PROMPT_PATH),
        payload=payload,
        description=f"project-level judge {payload.get('itb_scope', '')}".strip(),
    )


def _judge_payload(
    client: Any,
    model: str,
    prompt: str,
    payload: dict[str, Any],
    description: str,
    retries: int = 2,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.0,
                max_completion_tokens=1200,
                response_format={"type": "json_object"},
            )
            parsed = parse_json_output(response.choices[0].message.content or "{}")
            return _normalize_scores(parsed)
        except Exception as exc:
            last_error = exc
            if attempt > retries:
                break
            logger.warning("{} failed on attempt {}/{}: {}", description, attempt, retries + 1, exc)
            time.sleep(0.5 * attempt)
    if last_error is not None:
        raise last_error
    raise AssertionError("unreachable")


def _normalize_scores(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "coverage_score": _normalize_score(value.get("coverage_score")),
        "purity_score": _normalize_score(value.get("purity_score")),
        "readiness_score": _normalize_score(value.get("readiness_score")),
        "final_score": _normalize_score(value.get("final_score")),
        "confidence": _clean(value.get("confidence")),
    }


def _normalize_score(value: Any) -> float | str:
    if value in ("", None):
        return ""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return ""
    return max(0.0, min(1.0, score))


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
