"""Helpers for parsing JSON returned by chat models."""

from __future__ import annotations

import json
from typing import Any


def parse_json_output(output: str) -> dict[str, Any]:
    """Parse a JSON object from a model response."""
    value = json.loads(output)
    if not isinstance(value, dict):
        raise ValueError("model response must be a JSON object")
    return value
