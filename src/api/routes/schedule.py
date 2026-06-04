"""Schedule service API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from schedule_service.candidate.candidate_extractor import extract_candidates
from schedule_service.generate._shared.resource_cache import get_schedule_activities
from schedule_service.generate.activity.loader import DEFAULT_SCHEDULE_PATH
from schedule_service.generate.schedule_generator import generate_schedule_file

router = APIRouter(prefix="/schedule", tags=["schedule"])

_OUTPUT_BASE = Path("output/schedule_service")
CACHE_DIR = _OUTPUT_BASE / "cache"
CANDIDATES_DIR = _OUTPUT_BASE / "candidates"
GENERATE_DIR = _OUTPUT_BASE / "generate"
ScheduleLimit = Annotated[
    int,
    Query(
        ge=0,
        description="Maximum number of input rows to process. Use 0 to process all rows.",
    ),
]



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
            examples=["output/current_test_env/Fadhili_MDL_classified.csv"],
        ),
    ],
    ntp_date: Annotated[
        str,
        Query(
            description=(
                "Real project NTP date in ISO format (e.g. 2024-01-15). "
                "All guide schedule template dates (anchored at 2007-03-01) are shifted "
                "by (ntp_date - 2007-03-01) to produce real-world FA/FC dates. "
                "If omitted, template dates are used as-is."
            ),
            examples=["2024-01-15"],
        ),
    ] = "",
    rule_csv: Annotated[
        str,
        Query(
            description=(
                "Optional path to a custom validation rule CSV. "
                "Defaults to data/schedule_service/raw/validation_rule.csv when omitted."
            ),
            examples=["data/schedule_service/raw/mock_validation_rule.csv"],
        ),
    ] = "",
    limit: ScheduleLimit = 0,
) -> dict[str, object]:
    """Generate FA/FC schedule date ranges from an MDL classified CSV."""
    input_path = _existing_path(input_csv)
    logger.info("Generating FA/FC date ranges from MDL classified CSV: {}", input_path)
    if ntp_date:
        logger.info("NTP date: {}", ntp_date)

    from schedule_service.generate.rule.loader import DEFAULT_RULE_PATH
    rule_path = _existing_path(rule_csv) if rule_csv else DEFAULT_RULE_PATH
    if rule_csv:
        logger.info("Using custom rule file: {}", rule_path)

    schedule_activities = get_schedule_activities(DEFAULT_SCHEDULE_PATH)
    xlsx_path, json_path, timing = generate_schedule_file(
        input_csv=input_path,
        schedule_activities=schedule_activities,
        output_dir=GENERATE_DIR,
        rule_path=rule_path,
        limit=limit,
        ntp_date=ntp_date,
        semantic_cache_dir=CACHE_DIR / "rule_semantic_cache",
        activity_cache_dir=CACHE_DIR / "activity_semantic_cache",
    )
    return _file_response("generated_schedule", input_path, xlsx_path, json_path, timing)


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
            examples=["output/current_test_env/output_match_all_projects_section6.csv"],
        ),
    ],
    score_threshold: Annotated[
        float,
        Query(
            description=(
                "Minimum score to include a matched document. "
                "New hybrid/semantic format uses Semantic score (0–1); recommended 0.75. "
                "Old format uses 최종점수 (can exceed 1); recommended 0.85."
            ),
        ),
    ] = 0.75,
    top_n: Annotated[
        int,
        Query(gt=0, le=100, description="Number of Matched_Doc_N columns to consider per row."),
    ] = 5,
    classify_with_llm: Annotated[
        bool,
        Query(
            description=(
                "Re-classify Equipment/Building/System/Deliverable using the MDL LLM classifier. "
                "Improves rule matching quality in /schedule/generate. Requires Azure OpenAI credentials."
            ),
        ),
    ] = False,
    limit: ScheduleLimit = 0,
) -> dict[str, object]:
    """Extract MDL candidates from ITB matching CSV and write a candidate CSV."""
    input_path = _existing_path(input_csv)
    logger.info("Extracting MDL candidates from: {}", input_path)

    csv_path, timing = extract_candidates(
        input_csv=input_path,
        output_dir=CANDIDATES_DIR,
        score_threshold=score_threshold,
        top_n=top_n,
        limit=limit,
        classify_with_llm=classify_with_llm,
    )
    return {
        "kind": "mdl_candidates",
        "input_path": str(input_path),
        "output_dir": str(csv_path.parent),
        "files": {"csv": str(csv_path)},
        "timing": timing,
    }


def _file_response(
    kind: str,
    input_path: Path,
    xlsx_path: Path,
    json_path: Path,
    timing: dict | None = None,
) -> dict[str, object]:
    """Build the API response for schedule service file outputs."""
    result: dict[str, object] = {
        "kind": kind,
        "input_path": str(input_path),
        "output_dir": str(xlsx_path.parent),
        "files": {
            "json": str(json_path),
            "xlsx": str(xlsx_path),
        },
    }
    if timing:
        result["timing"] = timing
    return result


def _existing_path(value: str) -> Path:
    """Resolve and validate a user-provided local input path."""
    path = Path(value)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {value}")
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"Input path is not a file: {value}")
    return path
