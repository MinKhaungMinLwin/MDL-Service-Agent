"""LLM validation for reranked schedule activity candidates."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from schedule_service.models import Candidate


class ScheduleLLMValidator:
    def __init__(self) -> None:
        _load_env_file(Path("00_current_work/current_test_env/.env"))
        from openai import AzureOpenAI

        endpoint = _required_env("AZURE_OPENAI_ENDPOINT")
        parsed = urlparse(endpoint)
        azure_endpoint = f"{parsed.scheme}://{parsed.netloc}/"
        self.deployment = _required_env("AZURE_OPENAI_CHAT_DEPLOYMENT")
        self.client = AzureOpenAI(
            api_key=_required_env("AZURE_OPENAI_API_KEY"),
            azure_endpoint=azure_endpoint,
            api_version=os.getenv("AZURE_OPENAI_CHAT_API_VERSION", "2024-12-01-preview"),
        )

    def select_activity(self, query_text: str, candidates: list[Candidate]) -> dict[str, str]:
        if not candidates:
            return _empty_selection("no_candidates")

        candidate_payload = [
            {
                "rank": index,
                "activity_id": candidate.activity.activity_id,
                "activity_name": candidate.activity.activity_name_clean or candidate.activity.activity_name,
                "wbs_path": candidate.activity.wbs_path,
                "start_date": candidate.activity.start_date,
                "finish_date": candidate.activity.finish_date,
                "rrf_score": round(candidate.rrf_score, 6),
            }
            for index, candidate in enumerate(candidates, start=1)
        ]

        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You validate schedule activity matches. Select exactly one candidate "
                        "from the provided list. Return only JSON with keys: "
                        "selected_activity_id, selected_rank, confidence, reason, status. "
                        "Use status=selected if one candidate is suitable; otherwise use "
                        "status=needs_review and still choose the closest candidate."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "search_query": query_text,
                            "candidates": candidate_payload,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )

        content = response.choices[0].message.content or "{}"
        parsed = _parse_json_object(content)
        return {
            "llm_selected_activity_id": str(parsed.get("selected_activity_id", "")),
            "llm_selected_rank": str(parsed.get("selected_rank", "")),
            "llm_confidence": str(parsed.get("confidence", "")),
            "llm_reason": str(parsed.get("reason", "")),
            "llm_status": str(parsed.get("status", "")),
        }


def _empty_selection(status: str = "") -> dict[str, str]:
    return {
        "llm_selected_activity_id": "",
        "llm_selected_rank": "",
        "llm_confidence": "",
        "llm_reason": "",
        "llm_status": status,
    }


def _parse_json_object(text: str) -> dict[str, object]:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            value = json.loads(text[start : end + 1])
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
