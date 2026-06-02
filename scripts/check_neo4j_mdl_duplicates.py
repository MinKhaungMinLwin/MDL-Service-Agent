"""Report duplicate MDL document nodes in Neo4j.

This script is read-only. It groups MDL nodes by document-level fields so we can
detect cases where Neo4j has multiple nodes for the same visible MDL document.
"""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from loguru import logger  # noqa: E402

from common.neo4j_client import Neo4jConnection  # noqa: E402
from matching_service.models import MatchingConfig  # noqa: E402

GROUP_KEYS = {
    "doc-id": ("doc_id",),
    "document": ("source_file", "document_no", "title"),
    "document-no-title": ("document_no", "title"),
    "title": ("title",),
}


@dataclass(frozen=True)
class DuplicateCheckConfig:
    """Runtime settings for checking duplicated MDL nodes."""

    label: str = MatchingConfig.node_label
    key: str = "document"
    limit: int = 50
    sample_size: int = 10
    excluded_source_text: str = ""

    def __post_init__(self) -> None:
        if self.key not in GROUP_KEYS:
            raise ValueError(f"key must be one of: {', '.join(sorted(GROUP_KEYS))}")
        if self.limit <= 0:
            raise ValueError("limit must be positive")
        if self.sample_size <= 0:
            raise ValueError("sample_size must be positive")
        _validate_label(self.label)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check duplicate MDL nodes in Neo4j.")
    parser.add_argument("--label", default=MatchingConfig.node_label)
    parser.add_argument(
        "--key",
        choices=sorted(GROUP_KEYS),
        default="document",
        help="Grouping key used to decide whether nodes are duplicates.",
    )
    parser.add_argument("--limit", type=int, default=50, help="Maximum duplicate groups to log.")
    parser.add_argument("--sample-size", type=int, default=10, help="Maximum nodes logged per duplicate group.")
    parser.add_argument(
        "--excluded-source-text",
        default="",
        help=(
            "Skip nodes whose source_file contains this text. "
            f"Use {MatchingConfig.excluded_source_text!r} to mimic matching search corpus."
        ),
    )
    parser.add_argument("--json-output", type=Path, help="Optional path to save the duplicate report as JSON.")
    args = parser.parse_args()

    config = DuplicateCheckConfig(
        label=args.label,
        key=args.key,
        limit=args.limit,
        sample_size=args.sample_size,
        excluded_source_text=args.excluded_source_text,
    )
    with Neo4jConnection() as conn:
        report = build_duplicate_report(conn, config)
    log_duplicate_report(report)
    if args.json_output:
        write_duplicate_report(report, args.json_output)


def build_duplicate_report(conn: Neo4jConnection, config: DuplicateCheckConfig) -> dict[str, Any]:
    """Return duplicate summary and sample groups for MDL document nodes."""
    fields = GROUP_KEYS[config.key]
    return {
        "label": config.label,
        "key": config.key,
        "fields": fields,
        "summary": _read_summary(conn, config, fields),
        "groups": _read_duplicate_groups(conn, config, fields),
    }


def log_duplicate_report(report: dict[str, Any]) -> None:
    """Log a duplicate report using loguru."""
    summary = report["summary"]
    logger.info("Neo4j label: {}", report["label"])
    logger.info("Duplicate key: {} ({})", report["key"], ", ".join(report["fields"]))
    logger.info("Duplicate groups: {}", summary["duplicate_groups"])
    logger.info("Duplicated nodes: {}", summary["duplicated_nodes"])
    logger.info("Extra duplicate nodes: {}", summary["extra_duplicate_nodes"])
    for index, group in enumerate(report["groups"], start=1):
        key = ", ".join(f"{field}={value}" for field, value in group["key"].items())
        logger.info("{}. count={} | {}", index, group["node_count"], key)
        logger.info("   different_fields={}", group["different_fields"])
        for sample in group["samples"]:
            logger.info(
                "   - doc_id={} | source_file={} | document_no={} | title={}",
                sample.get("doc_id"),
                sample.get("source_file"),
                sample.get("document_no"),
                sample.get("title"),
            )


def write_duplicate_report(report: dict[str, Any], output_path: Path) -> None:
    """Persist duplicate report as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved duplicate report: {}", output_path)


def _read_summary(
    conn: Neo4jConnection,
    config: DuplicateCheckConfig,
    fields: tuple[str, ...],
) -> dict[str, int]:
    query = f"""
    MATCH (n:`{config.label}`)
    WHERE $excluded_source_text = ""
       OR NOT coalesce(n.source_file, "") CONTAINS $excluded_source_text
    WITH {_field_projection(fields)}
    WHERE any(value IN key_values WHERE value <> "")
    WITH key_values, count(*) AS node_count
    WHERE node_count > 1
    RETURN count(*) AS duplicate_groups,
           coalesce(sum(node_count), 0) AS duplicated_nodes,
           coalesce(sum(node_count - 1), 0) AS extra_duplicate_nodes
    """
    with conn.session() as session:
        record = session.run(query, excluded_source_text=config.excluded_source_text).single()
    if record is None:
        return {"duplicate_groups": 0, "duplicated_nodes": 0, "extra_duplicate_nodes": 0}
    return {
        "duplicate_groups": int(record["duplicate_groups"]),
        "duplicated_nodes": int(record["duplicated_nodes"]),
        "extra_duplicate_nodes": int(record["extra_duplicate_nodes"]),
    }


def _read_duplicate_groups(
    conn: Neo4jConnection,
    config: DuplicateCheckConfig,
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    query = f"""
    MATCH (n:`{config.label}`)
    WHERE $excluded_source_text = ""
       OR NOT coalesce(n.source_file, "") CONTAINS $excluded_source_text
    WITH {_field_projection(fields)}, n
    WHERE any(value IN key_values WHERE value <> "")
    WITH key_values,
         count(*) AS node_count,
         collect({{
             doc_id: n.doc_id,
             source_file: n.source_file,
             document_no: n.document_no,
             title: n.title,
             deliverable: n.deliverable,
             system: n.system,
             equipment: n.equipment,
             building: n.building,
             study_survey: n.study_survey,
             others: n.others,
             text_content: n.text_content,
             embedding_length: size(n.embedding)
         }})[0..$sample_size] AS samples
    WHERE node_count > 1
    RETURN key_values, node_count, samples
    ORDER BY node_count DESC, key_values
    LIMIT $limit
    """
    with conn.session() as session:
        records = list(
            session.run(
                query,
                excluded_source_text=config.excluded_source_text,
                limit=config.limit,
                sample_size=config.sample_size,
            )
        )
    groups = []
    for record in records:
        samples = record["samples"]
        groups.append({
            "key": dict(zip(fields, record["key_values"], strict=True)),
            "node_count": int(record["node_count"]),
            "different_fields": _different_fields(samples),
            "different_field_values": _different_field_values(samples),
            "samples": samples,
        })
    return groups


def _field_projection(fields: tuple[str, ...]) -> str:
    values = ", ".join(f'coalesce(n.{field}, "")' for field in fields)
    return f"[{values}] AS key_values"


def _validate_label(label: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
        raise ValueError(f"Invalid Neo4j label: {label}")


def _different_fields(samples: list[dict[str, Any]]) -> list[str]:
    fields = sorted({field for sample in samples for field in sample})
    return [field for field in fields if len({_stable_value(sample.get(field)) for sample in samples}) > 1]


def _different_field_values(samples: list[dict[str, Any]]) -> dict[str, list[Any]]:
    result = {}
    for field in _different_fields(samples):
        values = []
        seen = set()
        for sample in samples:
            value = sample.get(field)
            stable = _stable_value(value)
            if stable not in seen:
                seen.add(stable)
                values.append(value)
        result[field] = values
    return result


def _stable_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


if __name__ == "__main__":
    main()
