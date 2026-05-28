"""LLM validation for reranked schedule activity candidates."""

from __future__ import annotations

import json

from common.config import load_env_file, required_env
from common.openai_client import build_azure_openai_client
from schedule_service.models import Candidate


class ScheduleLLMValidator:
    """Select the best schedule activity candidate with Azure OpenAI."""

    def __init__(self) -> None:
        """Create the Azure OpenAI chat client."""
        load_env_file()
        self.deployment = required_env("AZURE_OPENAI_CHAT_DEPLOYMENT")
        self.client = build_azure_openai_client(
            api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
            default_api_version="2024-12-01-preview",
        )

    def select_activity(self, query_text: str, candidates: list[Candidate]) -> dict[str, str]:
        """Return the LLM-selected activity metadata for one query."""
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
    """Return an empty LLM selection payload."""
    return {
        "llm_selected_activity_id": "",
        "llm_selected_rank": "",
        "llm_confidence": "",
        "llm_reason": "",
        "llm_status": status,
    }


def _parse_json_object(text: str) -> dict[str, object]:
    """Parse the first JSON object returned by the LLM."""
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

