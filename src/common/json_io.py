"""Small JSON file helpers shared by services."""

from __future__ import annotations

import json
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
    json_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
