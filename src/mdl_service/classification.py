"""LLM-backed classification of MDL document titles."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mdl_service.models import BatchClassification, ClassificationResult


def load_system_prompt(path: str | Path) -> str:
    """Load the classification prompt and enforce structured output mode."""
    content = Path(path).read_text(encoding="utf-8")
    input_template_index = content.rfind("## Input Template")
    if input_template_index != -1:
        content = content[:input_template_index].rstrip()
    return content + (
        "\n\n---\n\n"
        "## Output Mode (OVERRIDE - IMPORTANT)\n\n"
        "Ignore any CSV-related output rules above. "
        "Return your answer as a structured object with these fields per description:\n"
        "  - `equipment` (string, may be empty)\n"
        "  - `building` (string, may be empty)\n"
        "  - `system` (string, may be empty)\n"
        "  - `study_survey` (string, may be empty)\n"
        "  - `others` (string, may contain commas, slashes, parentheses)\n"
        "  - `deliverable` (string)\n\n"
        "For batch input (multiple numbered descriptions), return ONE object per description "
        "in the SAME ORDER as input, wrapped in the `results` array. "
        "The number of results MUST equal the number of input descriptions.\n\n"
        "Internal commas in any field are now SAFE - keep them as-is. "
        'Example: a building name like "Unit MV/LV Switchgear Building - 11, 12, 13" '
        "should be placed in `building` or `others` exactly as written, including the commas. "
        "Map the prompt's `Study/Survey` field to `study_survey`."
    )


class MDLClassifier:
    """Classify MDL titles through Azure OpenAI structured output."""

    def __init__(
        self,
        client: Any,
        model: str,
        system_prompt: str,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.max_retries = max_retries
        self.sleep = sleep

    def classify_titles(self, titles: list[str]) -> list[ClassificationResult]:
        """Classify titles, padding or truncating malformed batch responses."""
        if not titles:
            return []
        user_message = _build_user_message(titles)
        last_error = ""
        for attempt in range(self.max_retries):
            try:
                parsed = self._parse(user_message)
                if parsed is None:
                    last_error = "Parse failed: no parsed result"
                    break
                results = [ClassificationResult.from_response(result) for result in parsed.results]
                return _fit_result_count(results, len(titles))
            except Exception as exc:
                error_type = type(exc).__name__
                last_error = f"{error_type}: {exc}"
                if "400" in str(exc) or "content_filter" in str(exc).lower() or "BadRequest" in error_type:
                    break
                if attempt < self.max_retries - 1:
                    self.sleep(2 ** (attempt + 2) if "429" in str(exc) or "RateLimit" in error_type else 2)
        return [ClassificationResult(note=last_error[:200])] * len(titles)

    def _parse(self, user_message: str) -> BatchClassification | None:
        parameters = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            "response_format": BatchClassification,
            "temperature": 0.0,
            "max_completion_tokens": 16384,
        }
        try:
            response = self.client.chat.completions.parse(**parameters)
        except AttributeError:
            response = self.client.beta.chat.completions.parse(**parameters)
        return response.choices[0].message.parsed


def _build_user_message(titles: list[str]) -> str:
    if len(titles) == 1:
        return f'Description = "{titles[0]}"'
    descriptions = "\n".join(f'{index}. Description = "{title}"' for index, title in enumerate(titles, 1))
    return (
        f"Classify the following {len(titles)} descriptions. "
        f"Return exactly {len(titles)} objects in the `results` array in the same order.\n\n"
        f"{descriptions}"
    )


def _fit_result_count(results: list[ClassificationResult], expected_count: int) -> list[ClassificationResult]:
    if len(results) < expected_count:
        results.extend([ClassificationResult(note="missing from batch response")] * (expected_count - len(results)))
    return results[:expected_count]
