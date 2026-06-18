from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from clean_mdl_input import clean_row


def test_clean_row_fills_scope_from_title_when_structured_fields_are_empty() -> None:
    result = clean_row(
        {
            "Document No": "D-1",
            "Title": "PROCESS FLOW DIAGRAM FOR CCW SYSTEM",
            "Equipment": "",
            "System": "",
            "Building": "",
            "Others": "",
            "Deliverable": "",
        }
    )

    assert result.row["System"] == "Closed Cooling Water System"
    assert result.row["Deliverable"] == "Diagram"
    assert "filled_system_from_scope" in result.row["cleaning_actions"]
    assert result.row["needs_human_review"] == "false"


def test_clean_row_moves_deliverable_value_out_of_system() -> None:
    result = clean_row(
        {
            "Document No": "D-2",
            "Title": "HRSG DESIGN REPORT",
            "Equipment": "HRSG",
            "System": "report",
            "Building": "",
            "Others": "",
            "Deliverable": "",
        }
    )

    assert result.row["Equipment"] == "Heat Recovery Steam Generator"
    assert result.row["System"] == ""
    assert result.row["Deliverable"] == "DESIGN REPORT"
    assert "cleared_deliverable_value_from_system" in result.row["cleaning_actions"]


def test_clean_row_flags_scope_conflict_without_overwriting_existing_scope() -> None:
    result = clean_row(
        {
            "Document No": "D-3",
            "Title": "DCS CABLE LIST",
            "Equipment": "",
            "System": "Service Water System",
            "Building": "",
            "Others": "",
            "Deliverable": "LIST",
        }
    )

    assert result.row["System"] == "Service Water System"
    assert result.row["needs_human_review"] == "true"
    assert result.row["scope_status"] == "conflict"
    assert "structured_scope_conflict" in result.row["scope_conflict_reason"]


def test_clean_row_assigns_plant_general_for_common_documents() -> None:
    result = clean_row(
        {
            "Document No": "D-4",
            "Title": "SITE PLAN",
            "Equipment": "",
            "System": "",
            "Building": "",
            "Others": "",
            "Deliverable": "PLAN",
        }
    )

    assert result.row["System"] == "Plant General System"
    assert result.row["scope_status"] == "plant_general"
    assert result.row["needs_human_review"] == "false"
