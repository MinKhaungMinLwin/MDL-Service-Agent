"""Schedule service API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from schedule_service.activity_mapper import map_file
from schedule_service.candidate_extractor import extract_candidates
from schedule_service.schedule_generator import generate_schedule_file
from schedule_service.schedule_loader import DEFAULT_SCHEDULE_PATH, load_schedule_activities

router = APIRouter(prefix="/schedule", tags=["schedule"])

SCHEDULE_OUTPUT_DIR = Path("output") / "schedule_service"
ScheduleLimit = Annotated[
    int,
    Query(
        ge=0,
        description="Maximum number of input rows to process. Use 0 to process all rows.",
    ),
]


@router.post(
    "/map",
    summary="Map ITB requirements to schedule activities",
    description=(
        "Reads an ITB matching CSV, searches the cleaned CCPP guide schedule, "
        "reranks candidates, optionally lets the LLM select one activity, and writes "
        "schedule mapping JSON/XLSX files under output/schedule_service."
    ),
)
def schedule_map(
    input_csv: Annotated[
        str,
        Query(
            min_length=1,
            description="Path to an ITB matching CSV file inside the running app/container.",
            examples=["00_current_work/current_test_env/output/output_match_all_projects_section6.csv"],
        ),
    ],
    retrieve_k: Annotated[
        int,
        Query(gt=0, description="Number of candidates to retrieve from each search method before reranking."),
    ] = 50,
    top_k: Annotated[
        int,
        Query(gt=0, description="Number of reranked candidates passed to the LLM/final output."),
    ] = 10,
    use_semantic: Annotated[
        bool,
        Query(description="Use Azure OpenAI embeddings for semantic schedule search."),
    ] = True,
    use_llm: Annotated[
        bool,
        Query(description="Use the LLM to select one final activity from the reranked candidates."),
    ] = True,
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
    return _file_response("schedule_mapping", input_path, xlsx_path, json_path)


@router.post(
    "/generate",
    summary="Generate FA/FC date ranges from MDL classified CSV",
    description=(
        "Reads an MDL classified CSV (*_MDL_classified.csv), matches each document row "
        "against the validation rule table and CCPP guide schedule via BM25, and generates "
        "FA/FC date ranges. Output is written under output/schedule_service."
    ),
)
def schedule_generate(
    input_csv: Annotated[
        str,
        Query(
            min_length=1,
            description="Path to an MDL classified CSV file.",
            examples=["00_current_work/current_test_env/output/Fadhili_MDL_classified.csv"],
        ),
    ],
    limit: ScheduleLimit = 0,
) -> dict[str, object]:
    """Generate FA/FC schedule date ranges from an MDL classified CSV."""
    input_path = _existing_path(input_csv)
    logger.info("Generating FA/FC date ranges from MDL classified CSV: {}", input_path)

    schedule_activities = load_schedule_activities(DEFAULT_SCHEDULE_PATH)
    xlsx_path, json_path = generate_schedule_file(
        input_csv=input_path,
        schedule_activities=schedule_activities,
        output_dir=SCHEDULE_OUTPUT_DIR,
        limit=limit,
    )
    return _file_response("generated_schedule", input_path, xlsx_path, json_path)


@router.post(
    "/candidates",
    summary="Extract MDL document candidates from ITB matching CSV",
    description=(
        "Reads an ITB matching CSV (output_match_*.csv), parses Matched_Doc_1..N columns, "
        "filters by score threshold, deduplicates, and writes an MDL candidate CSV "
        "compatible with *_MDL_classified.csv that can be fed into /schedule/generate."
    ),
)
def schedule_candidates(
    input_csv: Annotated[
        str,
        Query(
            min_length=1,
            description="Path to an ITB matching CSV file.",
            examples=["00_current_work/current_test_env/output/output_match_all_projects_section6.csv"],
        ),
    ],
    score_threshold: Annotated[
        float,
        Query(gt=0.0, le=2.0, description="Minimum final score to include a matched document."),
    ] = 0.85,
    top_n: Annotated[
        int,
        Query(gt=0, le=20, description="Number of Matched_Doc_N columns to consider per row."),
    ] = 5,
    limit: ScheduleLimit = 0,
) -> dict[str, object]:
    """Extract MDL candidates from ITB matching CSV and write a candidate CSV."""
    input_path = _existing_path(input_csv)
    logger.info("Extracting MDL candidates from: {}", input_path)

    csv_path = extract_candidates(
        input_csv=input_path,
        output_dir=SCHEDULE_OUTPUT_DIR,
        score_threshold=score_threshold,
        top_n=top_n,
        limit=limit,
    )
    return {
        "kind": "mdl_candidates",
        "input_path": str(input_path),
        "output_dir": str(csv_path.parent),
        "files": {"csv": str(csv_path)},
    }


def _file_response(kind: str, input_path: Path, xlsx_path: Path, json_path: Path) -> dict[str, object]:
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
