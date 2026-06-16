"""Azure-backed :class:`JudgeProvider` for the rule_generic LLM judge.

Kept separate from ``generic_judge`` so the bucketing / verdict logic stays importable
and testable without the ``openai`` dependency or Azure credentials.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from common.config import required_env
from common.llm_json import parse_json_output
from common.openai_client import build_azure_openai_client
from common.prompts import load_prompt
from schedule_service.generate.rule.generic_judge import (
    BUCKET_AMBIG,
    VERDICT_GENERIC_OK,
    VERDICT_UNCERTAIN,
    VERDICT_USE_SPECIFIC,
    GenericVerdict,
    JudgePayload,
)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "rule_generic_judge.md"
_VALID_VERDICTS = {VERDICT_GENERIC_OK, VERDICT_USE_SPECIFIC, VERDICT_UNCERTAIN}
_LLM_CHUNK = 15


class LLMJudgeProvider:
    """Adjudicate G_AMBIG payloads with an Azure chat model (temperature 0, JSON mode)."""

    def __init__(self, client=None, model: str = "", prompt: str = "", chunk: int = _LLM_CHUNK) -> None:
        self._client = client or build_azure_openai_client("AZURE_OPENAI_API_VERSION", "2024-10-21")
        self._model = model or required_env("AZURE_OPENAI_CHAT_DEPLOYMENT")
        self._prompt = prompt or load_prompt(_PROMPT_PATH)
        self._chunk = chunk

    def judge(self, payloads: list[JudgePayload]) -> dict[str, GenericVerdict]:
        results: dict[str, GenericVerdict] = {}
        by_sig = {p.signature: p for p in payloads}
        for start in range(0, len(payloads), self._chunk):
            chunk = payloads[start : start + self._chunk]
            logger.info(
                "rule_generic judge: items {}-{} of {}", start + 1, start + len(chunk), len(payloads)
            )
            try:
                parsed = self._call(chunk)
            except Exception as exc:  # noqa: BLE001 — fail safe: leave chunk uncertain
                logger.warning("rule_generic judge chunk failed ({}); leaving as uncertain", exc)
                continue
            for item in parsed.get("results", []):
                verdict = self._to_verdict(item, by_sig)
                if verdict is not None:
                    results[item["id"]] = verdict
        return results

    def _call(self, chunk: list[JudgePayload]) -> dict:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self._prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"items": [p.as_prompt_item() for p in chunk]}, ensure_ascii=False
                    ),
                },
            ],
            temperature=0.0,
            max_completion_tokens=min(8192, 300 * len(chunk)),
            response_format={"type": "json_object"},
        )
        return parse_json_output(resp.choices[0].message.content or "{}")

    @staticmethod
    def _to_verdict(item: dict, by_sig: dict[str, JudgePayload]) -> GenericVerdict | None:
        sig = item.get("id")
        if not isinstance(sig, str) or sig not in by_sig:
            return None
        verdict = str(item.get("verdict", "")).strip()
        if verdict not in _VALID_VERDICTS:
            verdict = VERDICT_UNCERTAIN
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        chosen = str(item.get("chosen_rule", "")).strip()
        # Guard: chosen_rule must be one of the competing keywords we offered.
        allowed = {c["keyword"] for c in by_sig[sig].competing}
        if verdict == VERDICT_USE_SPECIFIC and chosen not in allowed:
            verdict, chosen, confidence = VERDICT_UNCERTAIN, "", 0.0
        return GenericVerdict(
            bucket=BUCKET_AMBIG,
            verdict=verdict,
            chosen_rule_keyword=chosen,
            confidence=max(0.0, min(1.0, confidence)),
            rationale=str(item.get("rationale", "")).strip()[:200],
            competing_count=len(by_sig[sig].competing),
        )
