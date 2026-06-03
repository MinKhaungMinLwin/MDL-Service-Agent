"""Delete duplicated MDL document nodes in Neo4j.

Duplicates are detected by document-level identity:
source_file + document_no + title.
"""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from loguru import logger  # noqa: E402

from common.neo4j_client import Neo4jConnection  # noqa: E402
from matching_service.models import MatchingConfig  # noqa: E402

DUPLICATE_KEY_FIELDS = ("source_file", "document_no", "title")


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete duplicate MDL document nodes in Neo4j.")
    parser.add_argument("--label", default=MatchingConfig.node_label)
    parser.add_argument("--source-file", default="", help="Optional source_file filter, e.g. Karabatan_MDL.xlsm.")
    parser.add_argument("--report-output", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()

    _validate_label(args.label)
    with Neo4jConnection() as conn:
        report = dedupe_mdl_documents(conn, args.label, args.source_file)
    log_report(report)
    if args.report_output:
        write_report(report, args.report_output)


def dedupe_mdl_documents(conn: Neo4jConnection, label: str, source_file: str) -> dict[str, Any]:
    """Keep one node per document-level key and delete the rest."""
    groups = _read_duplicate_groups(conn, label, source_file)
    delete_element_ids = [node["element_id"] for group in groups for node in group["delete"]]
    deleted_count = _delete_nodes(conn, delete_element_ids)
    return {
        "label": label,
        "duplicate_key_fields": DUPLICATE_KEY_FIELDS,
        "source_file": source_file,
        "duplicate_groups": len(groups),
        "planned_delete_nodes": len(delete_element_ids),
        "deleted_nodes": deleted_count,
        "groups": groups,
    }


def _read_duplicate_groups(conn: Neo4jConnection, label: str, source_file: str) -> list[dict[str, Any]]:
    query = f"""
    MATCH (n:`{label}`)
    WHERE $source_file = "" OR coalesce(n.source_file, "") = $source_file
    WITH [{_key_projection()}] AS key_values, n
    WHERE any(value IN key_values WHERE value <> "")
    WITH key_values,
         collect({{
             element_id: elementId(n),
             doc_id: n.doc_id,
             source_file: n.source_file,
             document_no: n.document_no,
             title: n.title
         }}) AS nodes,
         count(*) AS node_count
    WHERE node_count > 1
    RETURN key_values, node_count, nodes
    ORDER BY key_values
    """
    with conn.session() as session:
        records = list(session.run(query, source_file=source_file))

    groups = []
    for record in records:
        nodes = sorted(record["nodes"], key=_node_sort_key)
        groups.append(
            {
                "key": dict(zip(DUPLICATE_KEY_FIELDS, record["key_values"], strict=True)),
                "node_count": int(record["node_count"]),
                "keep": nodes[0],
                "delete": nodes[1:],
            }
        )
    return groups


def _delete_nodes(conn: Neo4jConnection, element_ids: list[str]) -> int:
    if not element_ids:
        return 0
    with conn.session() as session:
        result = session.run(
            """
            MATCH (n)
            WHERE elementId(n) IN $element_ids
            DETACH DELETE n
            RETURN count(*) AS deleted_count
            """,
            element_ids=element_ids,
        ).single()
    return int(result["deleted_count"]) if result else 0


def log_report(report: dict[str, Any]) -> None:
    """Log dedupe result."""
    logger.info("Neo4j label: {}", report["label"])
    logger.info("Duplicate key fields: {}", ", ".join(report["duplicate_key_fields"]))
    logger.info("Source file filter: {}", report["source_file"] or "<all>")
    logger.info("Duplicate groups: {}", report["duplicate_groups"])
    logger.info("Planned delete nodes: {}", report["planned_delete_nodes"])
    logger.info("Deleted nodes: {}", report["deleted_nodes"])
    for index, group in enumerate(report["groups"][:20], start=1):
        key = ", ".join(f"{field}={value}" for field, value in group["key"].items())
        logger.info("{}. count={} | {}", index, group["node_count"], key)
        logger.info("   keep={}", group["keep"]["doc_id"])
        logger.info("   delete={}", [node["doc_id"] for node in group["delete"]])


def write_report(report: dict[str, Any], output_path: Path) -> None:
    """Persist dedupe report as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved dedupe report: {}", output_path)


def _key_projection() -> str:
    return ", ".join(f'coalesce(n.{field}, "")' for field in DUPLICATE_KEY_FIELDS)


def _node_sort_key(node: dict[str, Any]) -> tuple[int, str]:
    return (_doc_id_suffix(str(node.get("doc_id") or "")), str(node.get("doc_id") or ""))


def _doc_id_suffix(doc_id: str) -> int:
    match = re.search(r"_(\d+)$", doc_id)
    return int(match.group(1)) if match else 10**12


def _validate_label(label: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
        raise ValueError(f"Invalid Neo4j label: {label}")


if __name__ == "__main__":
    main()
