"""Export a Neo4j graph to files and import it into another Neo4j instance.

This script is intended for cloning the current remote Neo4j data into a local
Docker Neo4j database through Bolt credentials. It does not modify the source
database.
"""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from loguru import logger  # noqa: E402

from common.config import load_env_file  # noqa: E402
from common.neo4j_client import Neo4jConnection  # noqa: E402

DEFAULT_EXPORT_DIR = Path("output") / "current_test_env" / "neo4j_export"
NODES_FILE = "nodes.jsonl"
RELATIONSHIPS_FILE = "relationships.jsonl"
SCHEMA_FILE = "schema.json"
SUMMARY_FILE = "summary.json"
MIGRATION_ID_PROPERTY = "__migration_id"


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="Clone Neo4j graph data through Bolt export/import files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export the source Neo4j graph to local files.")
    _add_connection_args(export_parser, prefix="", default_local=False)
    export_parser.add_argument("--output-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    export_parser.add_argument("--fetch-size", type=int, default=1000)

    import_parser = subparsers.add_parser("import", help="Import exported graph files into local Neo4j.")
    _add_connection_args(import_parser, prefix="", default_local=True)
    import_parser.add_argument("--input-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    import_parser.add_argument("--batch-size", type=int, default=500)
    import_parser.add_argument(
        "--clear-local",
        action="store_true",
        help="Delete all nodes and relationships in the target database before importing.",
    )
    import_parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="Import data only and skip recreating exported indexes/constraints.",
    )

    verify_parser = subparsers.add_parser("verify", help="Compare exported summary with a target Neo4j database.")
    _add_connection_args(verify_parser, prefix="", default_local=True)
    verify_parser.add_argument("--input-dir", type=Path, default=DEFAULT_EXPORT_DIR)

    args = parser.parse_args()
    if args.command == "export":
        export_graph(_connection_from_args(args), args.output_dir, args.fetch_size)
    elif args.command == "import":
        import_graph(
            conn=_connection_from_args(args),
            input_dir=args.input_dir,
            batch_size=args.batch_size,
            clear_local=args.clear_local,
            import_schema=not args.skip_schema,
        )
    elif args.command == "verify":
        verify_graph(_connection_from_args(args), args.input_dir)


def export_graph(conn: Neo4jConnection, output_dir: Path, fetch_size: int) -> None:
    """Export all nodes, relationships, and schema metadata to files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    nodes_path = output_dir / NODES_FILE
    relationships_path = output_dir / RELATIONSHIPS_FILE
    schema_path = output_dir / SCHEMA_FILE
    summary_path = output_dir / SUMMARY_FILE

    with conn:
        summary = {
            "nodes": _export_nodes(conn, nodes_path, fetch_size),
            "relationships": _export_relationships(conn, relationships_path, fetch_size),
            "schema": _export_schema(conn, schema_path),
        }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved migration summary: {}", summary_path)


def import_graph(
    conn: Neo4jConnection,
    input_dir: Path,
    batch_size: int,
    clear_local: bool,
    import_schema: bool,
) -> None:
    """Import exported graph files into a target Neo4j database."""
    nodes_path = input_dir / NODES_FILE
    relationships_path = input_dir / RELATIONSHIPS_FILE
    schema_path = input_dir / SCHEMA_FILE
    _require_file(nodes_path)
    _require_file(relationships_path)
    if import_schema:
        _require_file(schema_path)
    if not clear_local:
        raise ValueError("Use --clear-local to make the target database match the exported source database")

    with conn:
        _drop_schema(conn)
        _clear_database(conn)
        _import_nodes(conn, nodes_path, batch_size)
        _import_relationships(conn, relationships_path, batch_size)
        _remove_migration_ids(conn)
        if import_schema:
            _import_schema(conn, schema_path)
    logger.info("Import completed from {}", input_dir)


def verify_graph(conn: Neo4jConnection, input_dir: Path) -> None:
    """Compare local database counts with an exported summary file."""
    summary_path = input_dir / SUMMARY_FILE
    _require_file(summary_path)
    expected = json.loads(summary_path.read_text(encoding="utf-8"))
    with conn:
        actual = _read_database_summary(conn)

    expected_nodes = expected["nodes"]
    expected_relationships = expected["relationships"]
    logger.info("Expected nodes: {}", expected_nodes["count"])
    logger.info("Actual nodes: {}", actual["nodes"]["count"])
    logger.info("Expected relationships: {}", expected_relationships["count"])
    logger.info("Actual relationships: {}", actual["relationships"]["count"])
    logger.info("Node counts match: {}", expected_nodes["count"] == actual["nodes"]["count"])
    logger.info("Relationship counts match: {}", expected_relationships["count"] == actual["relationships"]["count"])
    logger.info("Label distribution matches: {}", expected_nodes["labels"] == actual["nodes"]["labels"])
    logger.info(
        "Relationship type distribution matches: {}",
        expected_relationships["types"] == actual["relationships"]["types"],
    )


def _export_nodes(conn: Neo4jConnection, output_path: Path, fetch_size: int) -> dict[str, Any]:
    logger.info("Exporting nodes to {}", output_path)
    count = 0
    label_counts: Counter[str] = Counter()
    label_set_counts: Counter[str] = Counter()
    query = """
    MATCH (n)
    RETURN elementId(n) AS element_id,
           labels(n) AS labels,
           properties(n) AS properties
    """
    with conn.session() as session, open(output_path, "w", encoding="utf-8") as file:
        result = session.run(query, fetch_size=fetch_size)
        for record in result:
            labels = list(record["labels"])
            row = {
                "element_id": record["element_id"],
                "labels": labels,
                "properties": _json_safe(record["properties"]),
            }
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
            label_counts.update(labels)
            label_set_counts[_label_set_key(labels)] += 1
            if count % fetch_size == 0:
                logger.info("Exported {} nodes", count)
    logger.info("Exported {} nodes", count)
    return {
        "count": count,
        "labels": dict(sorted(label_counts.items())),
        "label_sets": dict(sorted(label_set_counts.items())),
    }


def _export_relationships(conn: Neo4jConnection, output_path: Path, fetch_size: int) -> dict[str, Any]:
    logger.info("Exporting relationships to {}", output_path)
    count = 0
    type_counts: Counter[str] = Counter()
    query = """
    MATCH (a)-[r]->(b)
    RETURN elementId(r) AS element_id,
           elementId(a) AS start_id,
           elementId(b) AS end_id,
           type(r) AS type,
           properties(r) AS properties
    """
    with conn.session() as session, open(output_path, "w", encoding="utf-8") as file:
        result = session.run(query, fetch_size=fetch_size)
        for record in result:
            relationship_type = record["type"]
            row = {
                "element_id": record["element_id"],
                "start_id": record["start_id"],
                "end_id": record["end_id"],
                "type": relationship_type,
                "properties": _json_safe(record["properties"]),
            }
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
            type_counts[relationship_type] += 1
            if count % fetch_size == 0:
                logger.info("Exported {} relationships", count)
    logger.info("Exported {} relationships", count)
    return {"count": count, "types": dict(sorted(type_counts.items()))}


def _export_schema(conn: Neo4jConnection, output_path: Path) -> dict[str, Any]:
    logger.info("Exporting schema to {}", output_path)
    with conn.session() as session:
        constraints = session.run("SHOW CONSTRAINTS").data()
        indexes = session.run("SHOW INDEXES").data()
    schema = {
        "constraints": _json_safe(constraints),
        "indexes": _json_safe(indexes),
    }
    output_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "constraints": len(constraints),
        "indexes": len(indexes),
    }


def _clear_database(conn: Neo4jConnection) -> None:
    logger.info("Clearing target database")
    with conn.session() as session:
        session.run("MATCH (n) DETACH DELETE n")


def _drop_schema(conn: Neo4jConnection) -> None:
    logger.info("Dropping existing target indexes and constraints")
    with conn.session() as session:
        constraints = session.run("SHOW CONSTRAINTS").data()
        indexes = session.run("SHOW INDEXES").data()
        for constraint in constraints:
            name = constraint.get("name")
            if name:
                session.run(f"DROP CONSTRAINT `{_escape_identifier(name)}` IF EXISTS")
        for index in indexes:
            name = index.get("name")
            if name and index.get("type") != "LOOKUP":
                session.run(f"DROP INDEX `{_escape_identifier(name)}` IF EXISTS")


def _import_nodes(conn: Neo4jConnection, nodes_path: Path, batch_size: int) -> None:
    logger.info("Importing nodes from {}", nodes_path)
    total = 0
    for batch in _read_jsonl_batches(nodes_path, batch_size):
        rows_by_labels = _group_rows_by_labels(batch)
        with conn.session() as session:
            for labels, rows in rows_by_labels.items():
                session.run(_create_nodes_query(labels), rows=rows)
        total += len(batch)
        logger.info("Imported {} nodes", total)


def _import_relationships(conn: Neo4jConnection, relationships_path: Path, batch_size: int) -> None:
    logger.info("Importing relationships from {}", relationships_path)
    total = 0
    for batch in _read_jsonl_batches(relationships_path, batch_size):
        rows_by_type = _group_rows_by_type(batch)
        with conn.session() as session:
            for relationship_type, rows in rows_by_type.items():
                session.run(_create_relationships_query(relationship_type), rows=rows)
        total += len(batch)
        logger.info("Imported {} relationships", total)


def _remove_migration_ids(conn: Neo4jConnection) -> None:
    logger.info("Removing temporary migration IDs")
    with conn.session() as session:
        session.run(f"MATCH (n) REMOVE n.{MIGRATION_ID_PROPERTY}")


def _import_schema(conn: Neo4jConnection, schema_path: Path) -> None:
    logger.info("Recreating schema from {}", schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    statements = _schema_create_statements(schema)
    with conn.session() as session:
        for statement in statements:
            logger.info("Running schema statement: {}", _one_line(statement))
            session.run(statement)
    logger.info("Recreated {} schema statements", len(statements))


def _schema_create_statements(schema: dict[str, Any]) -> list[str]:
    statements = []
    for constraint in schema.get("constraints", []):
        statement = constraint.get("createStatement")
        if statement:
            statements.append(statement)
    for index in schema.get("indexes", []):
        statement = index.get("createStatement")
        if statement and index.get("type") != "LOOKUP":
            statements.append(statement)
    return statements


def _read_database_summary(conn: Neo4jConnection) -> dict[str, Any]:
    with conn.session() as session:
        node_count = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
        relationship_count = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
        labels = session.run(
            """
            MATCH (n)
            UNWIND labels(n) AS label
            RETURN label, count(*) AS count
            ORDER BY label
            """
        ).data()
        relationship_types = session.run(
            """
            MATCH ()-[r]->()
            RETURN type(r) AS type, count(*) AS count
            ORDER BY type
            """
        ).data()
    return {
        "nodes": {
            "count": int(node_count),
            "labels": {row["label"]: int(row["count"]) for row in labels},
        },
        "relationships": {
            "count": int(relationship_count),
            "types": {row["type"]: int(row["count"]) for row in relationship_types},
        },
    }


def _create_nodes_query(labels: tuple[str, ...]) -> str:
    labels_clause = "".join(f":`{_escape_identifier(label)}`" for label in labels)
    return f"""
    UNWIND $rows AS row
    CREATE (n{labels_clause})
    SET n = row.properties
    SET n.{MIGRATION_ID_PROPERTY} = row.element_id
    """


def _create_relationships_query(relationship_type: str) -> str:
    return f"""
    UNWIND $rows AS row
    MATCH (start {{{MIGRATION_ID_PROPERTY}: row.start_id}})
    MATCH (end {{{MIGRATION_ID_PROPERTY}: row.end_id}})
    CREATE (start)-[r:`{_escape_identifier(relationship_type)}`]->(end)
    SET r = row.properties
    """


def _group_rows_by_labels(rows: list[dict[str, Any]]) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get("labels", []))].append(row)
    return dict(grouped)


def _group_rows_by_type(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row["type"])].append(row)
    return dict(grouped)


def _read_jsonl_batches(path: Path, batch_size: int) -> Iterator[list[dict[str, Any]]]:
    batch = []
    with open(path, encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            batch.append(json.loads(line))
            if len(batch) >= batch_size:
                yield batch
                batch = []
    if batch:
        yield batch


def _connection_from_args(args: argparse.Namespace) -> Neo4jConnection:
    return Neo4jConnection(
        uri=args.uri,
        user=args.user,
        password=args.password,
        database=args.database,
        max_pool_size=args.max_pool_size,
    )


def _add_connection_args(parser: argparse.ArgumentParser, prefix: str, default_local: bool) -> None:
    env_prefix = "LOCAL_NEO4J" if default_local else "NEO4J"
    default_uri = os.getenv(f"{env_prefix}_URI")
    default_user = os.getenv(f"{env_prefix}_USER")
    default_password = os.getenv(f"{env_prefix}_PASSWORD")
    default_database = os.getenv(f"{env_prefix}_DATABASE")
    if default_local:
        default_uri = default_uri or "bolt://localhost:7687"
        default_user = default_user or os.getenv("NEO4J_USER")
        default_password = default_password or os.getenv("NEO4J_PASSWORD")
        default_database = default_database or os.getenv("NEO4J_DATABASE")
    parser.add_argument(f"--{prefix}uri", default=default_uri)
    parser.add_argument(f"--{prefix}user", default=default_user)
    parser.add_argument(f"--{prefix}password", default=default_password)
    parser.add_argument(f"--{prefix}database", default=default_database)
    parser.add_argument(f"--{prefix}max-pool-size", type=int, default=int(os.getenv("NEO4J_MAX_POOL_SIZE", "50")))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _label_set_key(labels: list[str]) -> str:
    return "|".join(labels) if labels else "<no labels>"


def _escape_identifier(value: str) -> str:
    return value.replace("`", "``")


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)


if __name__ == "__main__":
    main()
