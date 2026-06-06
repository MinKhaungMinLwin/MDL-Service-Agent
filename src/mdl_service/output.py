"""Write classified MDL output artifacts."""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any

from mdl_service.models import ACC_FILTER_FIELDNAMES, CATALOG_FIELDNAMES, CLASSIFIED_FIELDNAMES


def write_classified_csv(output_path: str | Path, rows: list[dict[str, str]]) -> None:
    """Write classified MDL rows with stable downstream-compatible columns."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CLASSIFIED_FIELDNAMES, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)


def write_catalog_outputs(output_dir: str | Path, rows: list[dict[str, Any]], stem: str = "mdl_catalog") -> None:
    """Write Neo4j MDL catalog rows as CSV."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / f"{stem}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CATALOG_FIELDNAMES, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)


def write_acc_filter_outputs(output_dir: str | Path, rows: list[dict[str, Any]]) -> None:
    """Write all ACC filter judgments and the positive ACC-only catalog."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    positive_rows = [row for row in rows if _is_true(row.get("Is ACC Related"))]
    _write_dict_csv(directory / "acc_mdl_filter_judgments.csv", ACC_FILTER_FIELDNAMES, rows)
    _write_dict_csv(directory / "acc_mdl_catalog.csv", ACC_FILTER_FIELDNAMES, positive_rows)


def _write_dict_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    last_error: OSError | None = None
    for attempt in range(1, 6):
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
                writer.writerows(rows)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5 * attempt)
    if last_error is not None:
        raise last_error


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "yes", "y", "1"}
