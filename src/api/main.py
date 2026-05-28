"""FastAPI entrypoint for the PDF parser service."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from loguru import logger

from schedule_service.guide_schedule_loader import DEFAULT_SCHEDULE_PATH, load_schedule_activities
from schedule_service.mdl_activity_mapper import map_file
from schedule_service.schedule_generator import generate_schedule_file

try:
    from parser_service.service import ParserOutput, parse_pdf_to_output
except ImportError:
    ParserOutput = object
    parse_pdf_to_output = None

try:
    from chunker_service.service import ChunkerOutput, chunk_docling_json_to_output
except ImportError:
    ChunkerOutput = object
    chunk_docling_json_to_output = None

app = FastAPI(title="Doosan MDL API")

UPLOAD_DIR = Path("output") / "parser_service" / "uploads"
OUTPUT_DIR = Path("output") / "parser_service" / "parsed"
CHUNK_OUTPUT_DIR = Path("output") / "chunker_service" / "chunks"
SCHEDULE_OUTPUT_DIR = Path("output") / "schedule_service"


@app.get("/health")
def health() -> dict[str, str]:
    """Return a basic service health check."""
    return {"status": "ok"}


PreviewPages = Annotated[int | None, Query(gt=0)]


@app.post("/parse")
def parse(file: Annotated[UploadFile, File(...)], preview_pages: PreviewPages = None) -> dict[str, object]:
    """Parse an uploaded PDF and return output file metadata."""
    if parse_pdf_to_output is None:
        raise HTTPException(status_code=503, detail="Parser service is not available.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    input_path = UPLOAD_DIR / Path(file.filename or "upload.pdf").name

    logger.info("Received PDF upload: {}", input_path.name)
    with input_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    parser_output = parse_pdf_to_output(
        input_path=input_path,
        output_dir=OUTPUT_DIR / input_path.stem,
        preview_pages=preview_pages,
    )
    return _response(parser_output)


MaxTokens = Annotated[int, Query(gt=0)]


@app.post("/chunk")
def chunk(document_id: Annotated[str, Query(min_length=1)], max_tokens: MaxTokens = 512) -> dict[str, object]:
    """Chunk a parser-service Docling JSON output and return chunk metadata."""
    if chunk_docling_json_to_output is None:
        raise HTTPException(status_code=503, detail="Chunker service is not available.")

    input_path = OUTPUT_DIR / document_id / "docling.json"
    chunker_output = chunk_docling_json_to_output(
        input_path=input_path,
        document_id=document_id,
        output_dir=CHUNK_OUTPUT_DIR / document_id,
        max_tokens=max_tokens,
    )
    return _chunk_response(chunker_output)


ScheduleLimit = Annotated[int, Query(ge=0)]
ScheduleK = Annotated[int, Query(gt=0)]


@app.post("/schedule/map")
def schedule_map(
    input_csv: Annotated[str, Query(min_length=1)],
    retrieve_k: ScheduleK = 50,
    top_k: ScheduleK = 10,
    use_semantic: bool = True,
    use_llm: bool = True,
    limit: ScheduleLimit = 0,
) -> dict[str, object]:
    """Map an ITB match CSV output to CCPP guide schedule activities."""
    input_path = _existing_path(input_csv)
    logger.info("Mapping schedule activities from CSV: {}", input_path)

    schedule_activities = load_schedule_activities(DEFAULT_SCHEDULE_PATH)
    xlsx_path, json_path = map_file(
        input_csv=input_path,
        schedule_activities=schedule_activities,
        output_dir=SCHEDULE_OUTPUT_DIR,
        retrieve_k=retrieve_k,
        top_k=top_k,
        use_semantic=use_semantic,
        use_llm=use_llm,
        limit=limit,
    )
    return _schedule_file_response("schedule_mapping", input_path, xlsx_path, json_path)


@app.post("/schedule/generate")
def schedule_generate(
    mapping_json: Annotated[str, Query(min_length=1)],
    limit: ScheduleLimit = 0,
) -> dict[str, object]:
    """Generate a baseline schedule output from a schedule mapping JSON file."""
    input_path = _existing_path(mapping_json)
    logger.info("Generating baseline schedule from mapping JSON: {}", input_path)

    schedule_activities = load_schedule_activities(DEFAULT_SCHEDULE_PATH)
    xlsx_path, json_path = generate_schedule_file(
        mapping_json=input_path,
        schedule_activities=schedule_activities,
        output_dir=SCHEDULE_OUTPUT_DIR,
        limit=limit,
    )
    return _schedule_file_response("generated_schedule", input_path, xlsx_path, json_path)


def _response(parser_output: ParserOutput) -> dict[str, object]:
    """Build the API response for a parser output."""
    return {
        "document_id": parser_output.document_id,
        "input_path": str(parser_output.input_path),
        "output_dir": str(parser_output.output_dir),
        "docling_version": parser_output.docling_version,
        "files": {
            "json": str(parser_output.json_path),
            "markdown": str(parser_output.markdown_path),
        },
    }


def _schedule_file_response(kind: str, input_path: Path, xlsx_path: Path, json_path: Path) -> dict[str, object]:
    """Build the API response for schedule service file outputs."""
    return {
        "kind": kind,
        "input_path": str(input_path),
        "output_dir": str(xlsx_path.parent),
        "files": {
            "json": str(json_path),
            "xlsx": str(xlsx_path),
        },
    }


def _existing_path(value: str) -> Path:
    """Resolve and validate a user-provided local input path."""
    path = Path(value)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {value}")
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"Input path is not a file: {value}")
    return path


def _chunk_response(chunker_output: ChunkerOutput) -> dict[str, object]:
    """Build the API response for a chunker output."""
    return {
        "document_id": chunker_output.document_id,
        "input_path": str(chunker_output.input_path),
        "output_dir": str(chunker_output.output_dir),
        "chunker": chunker_output.chunker,
        "max_tokens": chunker_output.max_tokens,
        "chunk_count": chunker_output.chunk_count,
        "files": {
            "chunks": str(chunker_output.chunks_path),
        },
    }
