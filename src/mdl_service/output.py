"""Write classified MDL output artifacts."""

from __future__ import annotations

import csv
from pathlib import Path

from mdl_service.models import CLASSIFIED_FIELDNAMES


def write_classified_csv(output_path: str | Path, rows: list[dict[str, str]]) -> None:
    """Write classified MDL rows with stable downstream-compatible columns."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CLASSIFIED_FIELDNAMES, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
