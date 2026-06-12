"""Command-line entrypoints for MDL classification and ingestion."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from common.config import env_int, required_env
from common.embedding_client import AzureEmbeddingService
from common.neo4j_client import Neo4jConnection
from common.openai_client import build_azure_openai_client
from mdl_service.acc_filter import DEFAULT_ACC_FILTER_PROMPT_PATH, load_acc_filter_prompt
from mdl_service.acc_filter_service import ACCFilterService
from mdl_service.classification import DEFAULT_CLASSIFICATION_PROMPT_PATH, MDLClassifier, load_system_prompt
from mdl_service.loader import list_excel_files
from mdl_service.models import CLASSIFIED_FIELDNAMES, DocumentTitle, MDLIngestConfig
from mdl_service.output import write_catalog_outputs, write_classified_csv
from mdl_service.repository import MDLRepository
from mdl_service.service import MDLClassificationService, MDLIngestService

DEFAULT_DATA_DIR = Path("data") / "current_test_env" / "data"
DEFAULT_OUTPUT_DIR = Path("output") / "current_test_env"
DEFAULT_CATALOG_OUTPUT_DIR = DEFAULT_OUTPUT_DIR / "mdl_catalog"
DEFAULT_ACC_EXPERIMENT_OUTPUT_DIR = DEFAULT_OUTPUT_DIR / "acc_experiment"
DEFAULT_CATALOG_PROJECTS = ("Fadhili", "R&N", "Turkistan")
DEFAULT_ACC_OUTPUT_DIR = DEFAULT_ACC_EXPERIMENT_OUTPUT_DIR / "mdl_filter"


def classify(argv: list[str] | None = None) -> None:
    """Classify MDL Excel files and write *_classified.csv outputs."""
    parser = argparse.ArgumentParser(description="Classify MDL workbook titles with Azure OpenAI.")
    parser.add_argument("requested_file", nargs="?", help="Optional workbook filename inside --data-dir.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=Path(os.getenv("PROMPT_FILE", DEFAULT_CLASSIFICATION_PROMPT_PATH)),
    )
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--batch-delay-seconds", type=float, default=1.0)
    parser.add_argument(
        "--retry-failed-from",
        type=Path,
        help="Optional existing *_classified.csv file. If set, only rows with Note are reclassified and merged back.",
    )
    args = parser.parse_args(argv)

    client = build_azure_openai_client(
        api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
        default_api_version="2024-12-01-preview",
        timeout=1200.0,
    )
    service = MDLClassificationService(
        classifier=MDLClassifier(
            client=client,
            model=required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
            system_prompt=load_system_prompt(args.prompt_file),
        ),
        batch_size=args.batch_size,
        max_concurrency=args.max_concurrency,
        batch_delay_seconds=args.batch_delay_seconds,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.retry_failed_from:
        retried_count = _retry_failed_classifications(service, args.retry_failed_from)
        print(f"[UPDATED] {args.retry_failed_from} ({retried_count} failed rows retried)")
        return
    for input_path in list_excel_files(args.data_dir, args.requested_file):
        if not input_path.exists():
            print(f"[ERROR] File not found: {input_path}")
            continue
        output_path = args.output_dir / f"{input_path.stem}_classified.csv"
        count = service.classify_file(input_path, output_path)
        print(f"[SAVED] {output_path} ({count} rows)")


def ingest(argv: list[str] | None = None) -> None:
    """Ingest classified MDL CSV files into Neo4j."""
    parser = argparse.ArgumentParser(description="Embed and ingest classified MDL CSV files into Neo4j.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--embedding-dimensions", type=int, default=env_int("EMBEDDING_DIMENSIONS", 1536))
    parser.add_argument("--max-concurrency", type=int, default=1)
    args = parser.parse_args(argv)

    config = MDLIngestConfig(
        embedding_dimensions=args.embedding_dimensions,
        max_concurrency=args.max_concurrency,
    )
    with Neo4jConnection() as conn:
        service = MDLIngestService(
            repository=MDLRepository(conn, config),
            embedding_service=AzureEmbeddingService(),
            config=config,
        )
        service.setup()
        count = service.ingest_directory(args.input_dir)
    print(f"Ingested {count} MDL documents into {config.node_label}.")


def export_catalog(argv: list[str] | None = None) -> None:
    """Export a clean MDL catalog from Neo4j."""
    parser = argparse.ArgumentParser(description="Export MDL documents from Neo4j into a clean catalog.")
    parser.add_argument(
        "--project",
        action="append",
        dest="projects",
        help="Project/source-file term to include. Repeat for multiple projects.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CATALOG_OUTPUT_DIR)
    parser.add_argument("--output-stem", default="mdl_catalog")
    parser.add_argument("--node-label", default=MDLIngestConfig().node_label)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    projects = args.projects or list(DEFAULT_CATALOG_PROJECTS)
    config = MDLIngestConfig(node_label=args.node_label)
    with Neo4jConnection() as conn:
        repository = MDLRepository(conn, config)
        records = repository.export_catalog(projects, limit=args.limit)

    rows = [_build_catalog_row(record, projects) for record in records]
    write_catalog_outputs(args.output_dir, rows, stem=args.output_stem)
    print(f"Exported {len(rows)} MDL documents from Neo4j to {args.output_dir}.")


def filter_acc(argv: list[str] | None = None) -> None:
    """Filter ACC-related MDL documents from Neo4j or an exported catalog."""
    parser = argparse.ArgumentParser(description="Use an LLM to filter ACC-related MDL catalog rows.")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional exported MDL catalog CSV. If omitted, rows are loaded directly from Neo4j.",
    )
    parser.add_argument(
        "--project",
        action="append",
        dest="projects",
        help="Project/source-file term to include when loading from Neo4j. Repeat for multiple projects.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ACC_OUTPUT_DIR)
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=Path(os.getenv("ACC_FILTER_PROMPT_FILE", DEFAULT_ACC_FILTER_PROMPT_PATH)),
    )
    parser.add_argument("--model", default=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"))
    parser.add_argument("--node-label", default=MDLIngestConfig().node_label)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-concurrency", type=int, default=1)
    args = parser.parse_args(argv)

    client = build_azure_openai_client(
        api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
        default_api_version="2024-12-01-preview",
        timeout=1200.0,
    )
    service = ACCFilterService(
        client=client,
        model=args.model or required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        system_prompt=load_acc_filter_prompt(args.prompt_file),
        batch_size=args.batch_size,
        max_concurrency=args.max_concurrency,
    )
    if args.input:
        count = service.filter_file(args.input, args.output_dir)
    else:
        projects = args.projects or list(DEFAULT_CATALOG_PROJECTS)
        with Neo4jConnection() as conn:
            repository = MDLRepository(conn, MDLIngestConfig(node_label=args.node_label))
            records = repository.export_catalog(projects, limit=args.limit)
        rows = [_build_catalog_row(record, projects) for record in records]
        count = service.filter_rows(rows, args.output_dir)
    print(f"Filtered {count} MDL catalog rows into {args.output_dir / 'acc_mdl_catalog.csv'}.")


def _build_catalog_row(record: dict, projects: list[str]) -> dict[str, str]:
    source_file = _clean(record.get("source_file"))
    return {
        "Project Name": _infer_project_name(source_file, projects),
        "Doc ID": _clean(record.get("doc_id")),
        "Source File": source_file,
        "Document No": _clean(record.get("document_no")),
        "Title": _clean(record.get("title")),
        "Equipment": _clean(record.get("equipment")),
        "Building": _clean(record.get("building")),
        "System": _clean(record.get("system")),
        "Study/Survey": _clean(record.get("study_survey")),
        "Others": _clean(record.get("others")),
        "Deliverable": _clean(record.get("deliverable")),
        "Text Content": _clean(record.get("text_content")),
    }


def _infer_project_name(source_file: str, projects: list[str]) -> str:
    source_file_lower = source_file.lower()
    for project in projects:
        if project.lower() in source_file_lower:
            return project
    return ""


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _retry_failed_classifications(service: MDLClassificationService, classified_csv_path: Path) -> int:
    rows = _read_classified_rows(classified_csv_path)
    indexed_titles = [
        (
            index,
            DocumentTitle(
                source_file=_clean(row.get("Source File")),
                sheet=_clean(row.get("Sheet")),
                document_no=_clean(row.get("Document No")),
                title=_clean(row.get("Title")),
            ),
        )
        for index, row in enumerate(rows)
        if _clean(row.get("Title")) and _clean(row.get("Note"))
    ]
    if not indexed_titles:
        return 0
    updated_rows = service.classify_titles([title for _, title in indexed_titles])
    for (index, _), updated_row in zip(indexed_titles, updated_rows, strict=True):
        rows[index] = updated_row
    write_classified_csv(classified_csv_path, rows)
    return len(indexed_titles)


def _read_classified_rows(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with open(path, newline="", encoding=encoding) as file:
                rows = list(csv.DictReader(file))
                return [{field: _clean(row.get(field)) for field in CLASSIFIED_FIELDNAMES} for row in rows]
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8-sig", b"", 0, 1, f"Unable to decode {path}")


if __name__ == "__main__":
    classify()
