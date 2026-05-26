from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, UploadFile
from loguru import logger

from parser_service.service import ParserOutput, parse_pdf_to_output

app = FastAPI(title="Doosan MDL Parser API")

UPLOAD_DIR = Path("output") / "parser_service" / "uploads"
OUTPUT_DIR = Path("output") / "parser_service" / "parsed"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/parse")
def parse(file: Annotated[UploadFile, File(...)], max_pages: int | None = None) -> dict[str, object]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    input_path = UPLOAD_DIR / Path(file.filename or "upload.pdf").name

    logger.info("Received PDF upload: {}", input_path.name)
    with input_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    parser_output = parse_pdf_to_output(
        input_path=input_path,
        output_dir=OUTPUT_DIR / input_path.stem,
        max_num_pages=max_pages,
    )
    return _response(parser_output)


def _response(parser_output: ParserOutput) -> dict[str, object]:
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
