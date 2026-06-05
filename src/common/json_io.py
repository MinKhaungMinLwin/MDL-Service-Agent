"""Small JSON file helpers shared by services."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> Any:
    """Read one UTF-8 JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_json_list(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSON list artifact, returning an empty list when it does not exist."""
    json_path = Path(path)
    if not json_path.exists():
        return []
    value = read_json(json_path)
    return value if isinstance(value, list) else []


def write_json(path: str | Path, value: Any) -> None:
    """Write one UTF-8 JSON artifact."""
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temp_path = json_path.with_name(f".{json_path.name}.{os.getpid()}.tmp")
    last_error: OSError | None = None
    for attempt in range(1, 6):
        try:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(json_path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5 * attempt)
    if last_error is not None:
        raise last_error
