"""Shared models for MDL classification and ingestion."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

CLASSIFIED_FIELDNAMES = [
    "Source File",
    "Sheet",
    "Document No",
    "Title",
    "Equipment",
    "Building",
    "System",
    "Study/Survey",
    "Others",
    "Deliverable",
    "Note",
]

CATALOG_FIELDNAMES = [
    "Project Name",
    "Doc ID",
    "Source File",
    "Document No",
    "Title",
    "Equipment",
    "Building",
    "System",
    "Study/Survey",
    "Others",
    "Deliverable",
    "Text Content",
]

ACC_FILTER_FIELDNAMES = [
    *CATALOG_FIELDNAMES,
    "Is ACC Related",
]


class DocumentClassification(BaseModel):
    """Structured classification returned by the LLM for one MDL title."""

    equipment: str = Field(description="Equipment scope (e.g., HRSG, ACC, GT, Pump). Empty string if none applies.")
    building: str = Field(
        description="Building or facility scope (e.g., Control Building, Pipe Rack). Empty string if none applies."
    )
    system: str = Field(description="System scope (e.g., Fuel Gas System, HVAC). Empty string if none applies.")
    study_survey: str = Field(
        description=(
            "Study/survey scope (e.g., HAZOP Study, Soil Investigation, Load Flow Study). Empty string if none applies."
        )
    )
    others: str = Field(
        description=(
            "Other specific technical subjects, target objects, or engineering scopes not covered by equipment, "
            "building, system, or study/survey. May contain commas, slashes, or special chars. "
            "Empty string if none applies."
        )
    )
    deliverable: str = Field(
        description=(
            "Document type or engineering output (e.g., P&ID, Datasheet, Sizing Calculation, Architectural Drawing)."
        )
    )


class BatchClassification(BaseModel):
    """Structured batch response preserving the input title order."""

    results: list[DocumentClassification]


@dataclass(frozen=True)
class ClassificationResult:
    """Normalized classification fields plus an optional processing note."""

    equipment: str = ""
    building: str = ""
    system: str = ""
    study_survey: str = ""
    others: str = ""
    deliverable: str = ""
    note: str = ""

    @classmethod
    def from_response(cls, result: DocumentClassification) -> ClassificationResult:
        return cls(
            equipment=result.equipment.strip(),
            building=result.building.strip(),
            system=result.system.strip(),
            study_survey=result.study_survey.strip(),
            others=result.others.strip(),
            deliverable=result.deliverable.strip(),
        )


@dataclass(frozen=True)
class DocumentTitle:
    """One MDL title extracted from an Excel worksheet."""

    source_file: str
    sheet: str
    document_no: str
    title: str

    def to_csv_row(self, classification: ClassificationResult) -> dict[str, str]:
        return {
            "Source File": self.source_file,
            "Sheet": self.sheet,
            "Document No": self.document_no,
            "Title": self.title,
            "Equipment": classification.equipment,
            "Building": classification.building,
            "System": classification.system,
            "Study/Survey": classification.study_survey,
            "Others": classification.others,
            "Deliverable": classification.deliverable,
            "Note": classification.note,
        }


@dataclass(frozen=True)
class MDLIngestConfig:
    """Runtime configuration for writing classified MDL documents to Neo4j."""

    node_label: str = "TestMDLDocument"
    constraint_name: str = "test_mdl_doc_id_unique"
    fulltext_index_name: str = "test_mdl_document_fulltext_idx"
    vector_index_name: str = "test_mdl_document_vector_idx"
    embedding_dimensions: int = 1536
    batch_size: int = 50

    def __post_init__(self) -> None:
        for value in (self.node_label, self.constraint_name, self.fulltext_index_name, self.vector_index_name):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
                raise ValueError(f"Invalid Neo4j identifier: {value}")
        if self.embedding_dimensions <= 0:
            raise ValueError("embedding_dimensions must be positive")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
