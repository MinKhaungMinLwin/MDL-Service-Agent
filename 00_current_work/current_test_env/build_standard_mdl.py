"""Build an integrated Standard MDL before ITB comparison.

This workflow uses the seven classified MDL CSV files under output/ and creates
a reviewable Standard MDL candidate with Vendor/EPC scope separation, four-level
structure, source traceability, and validation reports. It intentionally does
not perform ITB matching or C/E/I classification.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from openai import AzureOpenAI
from pydantic import BaseModel, Field

from mdl_runtime.config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_CHAT_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    OUTPUT_DIR,
    required,
)


PROJECT_FILES = {
    "Fadhili": "Fadhili_MDL_classified.csv",
    "Grati": "Grati_MDL_classified.csv",
    "Karabatan": "Karabatan_MDL_classified.csv",
    "Muara Tawar": "Muara Tawar_MDL_classified.csv",
    "R&N": "R&N_MDL_classified.csv",
    "Turkistan": "Turkistan_MDL_classified.csv",
    "Ukudu": "Ukudu_MDL_classified.csv",
}

PROJECT_ORDER = list(PROJECT_FILES.keys())

DISCIPLINE_ORDER = [
    "Civil/Structural",
    "Mechanical",
    "Piping",
    "Process",
    "Electrical",
    "Instrumentation & Control",
    "General",
]

SCOPE_ORDER = ["Vendor", "EPC"]

REQUIRED_COLUMNS = [
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

STANDARD_COLUMNS = [
    "No",
    "Discipline",
    "Document Type",
    "System",
    "Sub-System",
    "Sub-Sub System (Equipment)",
    "Standardized Document Title",
    "Scope Type",
    "Source Projects",
    "Source Document Nos",
    "Source Titles",
    "Evidence Type",
    "Validation Status",
    "Review Comment",
]

EXPERT_COLUMNS = [
    *STANDARD_COLUMNS,
    "Source Standard Nos",
    "Review Status",
    "Augmentation Reason",
]

AUDIT_COLUMNS = [
    "standard_no",
    "standardized_document_title",
    "source_project",
    "source_file",
    "sheet",
    "document_no",
    "source_title",
    "source_equipment",
    "source_building",
    "source_system",
    "source_study_survey",
    "source_others",
    "source_deliverable",
]

VALIDATION_COLUMNS = [
    "validation_type",
    "severity",
    "discipline",
    "scope_type",
    "system",
    "sub_system",
    "equipment",
    "document_type",
    "standardized_document_title",
    "reason",
    "recommended_action",
]

REJECTION_COLUMNS = [
    "source_project",
    "source_file",
    "sheet",
    "document_no",
    "source_title",
    "reason",
    "raw_payload",
]

SUMMARY_COLUMNS = ["metric", "value"]

EXPERT_SOURCE_DOCUMENT_NO = "EXPERT-INFERRED"

PILOT_GROUPS = {
    ("Mechanical", "Vendor", "Technical Data Sheet"),
    ("Mechanical", "Vendor", "General Arrangement Drawing"),
    ("Civil/Structural", "EPC", "Foundation Drawing"),
    ("Civil/Structural", "EPC", "Layout Drawing"),
}

NON_DOCUMENT_TITLE_PATTERNS = [
    re.compile(r"\bpo\s*기준\b", re.IGNORECASE),
    re.compile(r"\bpo\s*base(?:d)?\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}\s*월\s*\d{1,2}\s*일\b"),
    re.compile(r"\b\d{4}[-./]\d{1,2}[-./]\d{1,2}\b"),
    re.compile(r"제출\s*날짜"),
    re.compile(r"플기팀|구매팀"),
]

GENERIC_TITLE_EQUIPMENT = {"Plant General", "General Area", ""}


class LLMStandardGroup(BaseModel):
    discipline: str
    document_type: str
    system: str
    sub_system: str
    equipment: str
    standardized_document_title: str
    scope_type: str = Field(description="Vendor or EPC")
    source_standard_nos: list[int]
    merge_reason: str


class LLMStandardGroupList(BaseModel):
    items: list[LLMStandardGroup]


class ExpertGeneratedItem(BaseModel):
    discipline: str
    document_type: str
    system: str
    sub_system: str
    equipment: str
    standardized_document_title: str
    scope_type: str = Field(description="Vendor or EPC")
    evidence_type: str = Field(description="Source-Inferred or Expert-Inferred")
    source_standard_nos: list[int]
    generation_reason: str


class ExpertGeneratedItemList(BaseModel):
    items: list[ExpertGeneratedItem]


def normalize_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "n/a"}:
        return ""
    return re.sub(r"\s+", " ", text)


def normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", " ", normalize_cell(value).lower()).strip()


def join_unique(values: Iterable[object], separator: str = " | ") -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = normalize_cell(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return separator.join(result)


def join_unique_tokens(values: Iterable[object], separator: str = " | ") -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        for part in normalize_cell(value).split(separator):
            text = normalize_cell(part)
            if text and text not in seen:
                seen.add(text)
                result.append(text)
    return separator.join(result)


def sort_joined_projects(value: object, separator: str = " | ") -> str:
    tokens = [normalize_cell(part) for part in normalize_cell(value).split(separator)]
    tokens = [token for token in tokens if token]
    order = {project: index for index, project in enumerate(PROJECT_ORDER)}
    unique = list(dict.fromkeys(tokens))
    return separator.join(sorted(unique, key=lambda token: (order.get(token, len(order)), token)))


def build_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=required(AZURE_OPENAI_API_KEY, "AZURE_OPENAI_API_KEY"),
        timeout=600.0,
    )


def parse_json_response(content: str, model: type[BaseModel]) -> BaseModel:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    return model.model_validate_json(cleaned)


def parse_structured_response(response, model: type[BaseModel]) -> BaseModel:
    message = response.choices[0].message
    parsed = getattr(message, "parsed", None)
    if parsed is not None:
        return parsed
    return parse_json_response(message.content or "", model)


def load_classified_mdls(input_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[pd.DataFrame] = []
    rejections: list[dict[str, str]] = []

    for project, filename in PROJECT_FILES.items():
        path = input_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Required classified MDL not found: {path}")

        df = pd.read_csv(path).fillna("")
        for column in REQUIRED_COLUMNS:
            if column not in df.columns:
                rejections.append(
                    {
                        "source_project": project,
                        "source_file": filename,
                        "sheet": "",
                        "document_no": "",
                        "source_title": "",
                        "reason": f"missing_required_column:{column}",
                        "raw_payload": json.dumps({"columns": list(df.columns)}, ensure_ascii=False),
                    }
                )
                df[column] = ""

        df = df[REQUIRED_COLUMNS].copy()
        df["Source Project"] = project
        rows.append(df)

    source_df = pd.concat(rows, ignore_index=True)
    source_df["Title"] = source_df["Title"].map(normalize_cell)
    blank_title = source_df["Title"].eq("")
    for _, row in source_df[blank_title].iterrows():
        rejections.append(rejection_from_row(row, "empty_title"))
    source_df = source_df[~blank_title].reset_index(drop=True)

    non_document_title = source_df["Title"].map(is_non_document_title)
    for _, row in source_df[non_document_title].iterrows():
        rejections.append(rejection_from_row(row, "non_document_title"))
    source_df = source_df[~non_document_title].reset_index(drop=True)
    return source_df, pd.DataFrame(rejections, columns=REJECTION_COLUMNS)


def rejection_from_row(row: pd.Series, reason: str) -> dict[str, str]:
    return {
        "source_project": normalize_cell(row.get("Source Project")),
        "source_file": normalize_cell(row.get("Source File")),
        "sheet": normalize_cell(row.get("Sheet")),
        "document_no": normalize_cell(row.get("Document No")),
        "source_title": normalize_cell(row.get("Title")),
        "reason": reason,
        "raw_payload": json.dumps(row.to_dict(), ensure_ascii=False, sort_keys=True),
    }


def is_non_document_title(title: object) -> bool:
    text = normalize_cell(title)
    if not text:
        return True
    key = normalize_key(text)
    if key in {"-", "--", "tbd", "n a", "na", "none", "null"}:
        return True
    if any(pattern.search(text) for pattern in NON_DOCUMENT_TITLE_PATTERNS):
        return True
    words = [word for word in re.split(r"\s+", text) if word]
    if len(words) <= 2 and any(term in key for term in ["remark", "note", "date", "schedule 기준"]):
        return True
    return False


def infer_document_type(row: pd.Series) -> str:
    deliverable = normalize_cell(row.get("Deliverable"))
    if deliverable:
        return normalize_document_type(deliverable, row.get("Title"))

    title = normalize_key(row.get("Title"))
    rules = [
        ("Piping & Instrumentation Drawing", ["p id", "p i diagram", "piping instrumentation"]),
        ("General Arrangement Drawing", ["general arrangement", "ga drawing"]),
        ("Data Sheet", ["data sheet", "datasheet"]),
        ("Technical Specification", ["technical specification", "specification"]),
        ("Design Calculation", ["design calculation", "calculation"]),
        ("Layout Drawing", ["layout"]),
        ("Report", ["report"]),
        ("Study", ["study"]),
        ("Procedure", ["procedure"]),
        ("Manual", ["manual"]),
        ("Drawing", ["drawing"]),
        ("List", ["list"]),
        ("Schedule", ["schedule"]),
        ("Diagram", ["diagram"]),
    ]
    for document_type, markers in rules:
        if any(marker in title for marker in markers):
            return document_type
    return "Document"


def normalize_document_type(deliverable: object, title: object = "") -> str:
    text = normalize_cell(deliverable)
    key = normalize_key(" ".join([text, normalize_cell(title)]))
    rules = [
        ("Technical Data Sheet and Drawing", ["data sheet and drawing", "datasheet and drawing", "data sheet and characteristic curves and drawing"]),
        ("Piping & Instrumentation Drawing", ["piping instrumentation", "p id", "p i diagram", "p and id"]),
        ("Single Line Diagram", ["single line diagram", "sld"]),
        ("Logic Diagram", ["logic diagram", "control logic"]),
        ("Interlock Diagram", ["interlock diagram"]),
        ("Wiring Diagram", ["wiring diagram", "interconnection wiring"]),
        ("Cable Raceway Layout", ["cable raceway"]),
        ("Cable Schedule", ["cable schedule"]),
        ("Lighting Layout", ["lighting layout"]),
        ("Grounding Layout", ["grounding", "earthing", "lightning protection"]),
        ("Isometric Drawing", ["isometric", "iso drawing"]),
        ("Piping Support Drawing", ["piping support"]),
        ("Hook-Up Drawing", ["hook up", "hookup"]),
        ("Cause & Effect Matrix", ["cause effect", "cause and effect", "c e matrix"]),
        ("General Arrangement Drawing", ["general arrangement", "general layout", "ga drawing", "arrangement drawing", "arrangement"]),
        ("Layout Drawing", ["layout drawing", "layout", "plan section", "plan and section", "equipment plan"]),
        ("Reinforcement Drawing", ["reinforcement", "rebar", "re bar"]),
        ("Foundation Drawing", ["foundation", "footing"]),
        ("Detail Drawing", ["detail", "section", "elevation", "cladding", "shop drawing", "workshop drawing", "outline drawing", "assembly drawing"]),
        ("Drawing", ["drawing", "dwg"]),
        ("Design Calculation", ["design calculation", "sizing calculation", "calculation sheet", "calculation"]),
        ("Technical Data Sheet", ["technical data sheet", "data sheet", "datasheet"]),
        ("Technical Specification", ["technical specification", "specification"]),
        ("Performance Curve", ["performance curve", "curve"]),
        ("System Description", ["system description", "functional description", "description"]),
        ("Control Philosophy", ["control philosophy", "philosophy"]),
        ("Study", ["hazop", "hazid", "sil", "study"]),
        ("Survey Report", ["survey report", "investigation report"]),
        ("Report", ["report", "assessment", "analysis"]),
        ("Procedure", ["procedure"]),
        ("Manual", ["manual", "instruction"]),
        ("Packing List", ["packing list"]),
        ("Quality Dossier", ["quality dossier"]),
        ("Certificate", ["certificate"]),
        ("Register", ["register"]),
        ("Index", ["index"]),
        ("List", ["list"]),
        ("Schedule", ["schedule"]),
        ("Plan", ["plan"]),
        ("Diagram", ["diagram"]),
        ("BOM", ["bom", "bill of material"]),
        ("Dossier", ["dossier"]),
    ]
    for standard, markers in rules:
        if any(marker in key for marker in markers):
            return standard
    return title_case_engineering(text) if text else "Document"


def title_case_engineering(text: str) -> str:
    keep_upper = {
        "ACC",
        "HRSG",
        "GT",
        "GTG",
        "ST",
        "STG",
        "BFP",
        "CEP",
        "CWP",
        "CCWP",
        "DCS",
        "I&C",
        "P&ID",
        "GA",
        "HVAC",
        "O&M",
        "SIL",
        "HAZOP",
        "HSE",
        "FAT",
        "SAT",
        "MCC",
        "UPS",
        "DC",
        "AC",
    }
    words = []
    for word in normalize_cell(text).split():
        stripped = word.strip()
        if stripped.upper().strip("()") in keep_upper:
            words.append(stripped.upper())
        elif any(ch.isupper() for ch in stripped[1:]) or "&" in stripped or "/" in stripped:
            words.append(stripped)
        else:
            words.append(stripped[:1].upper() + stripped[1:].lower())
    return " ".join(words)


def infer_discipline(row: pd.Series, document_type: str) -> str:
    text = normalize_key(
        " ".join(
            normalize_cell(row.get(column))
            for column in ["Title", "Equipment", "Building", "System", "Study/Survey", "Others", "Deliverable"]
        )
    )
    doc = normalize_key(document_type)

    if any(term in text for term in ["foundation", "structural", "structure", "rebar", "reinforcement", "civil", "architectural", "building", "road", "drainage", "underground", "excavation", "concrete", "cladding"]):
        return "Civil/Structural"
    if any(term in text for term in ["piping", "pipe", "isometric", "stress analysis", "support schedule", "valve list"]):
        return "Piping"
    if any(term in text for term in ["instrument", "i c", "control logic", "dcs", "plc", "transmitter", "analyzer", "control valve", "junction box", "loop diagram", "hook up"]):
        return "Instrumentation & Control"
    if any(term in text for term in ["cable", "switchgear", "transformer", "electrical", "lighting", "grounding", "earthing", "motor control", "mcc", "ups", "battery", "relay", "short circuit", "load flow"]):
        return "Electrical"
    if any(term in text for term in ["heat balance", "water balance", "process flow", "pfd", "process", "hazop", "hazid", "sil", "operating philosophy"]):
        return "Process"
    if any(term in doc for term in ["procedure", "manual", "plan", "list"]) and not normalize_cell(row.get("Equipment")):
        return "General"
    return "Mechanical"


def infer_scope_type(row: pd.Series, discipline: str, document_type: str, inferred_equipment: str = "") -> str:
    text = normalize_key(
        " ".join(
            [
                *(normalize_cell(row.get(column)) for column in ["Title", "Equipment", "Building", "System", "Study/Survey", "Others", "Deliverable"]),
                normalize_cell(document_type),
                normalize_cell(inferred_equipment),
            ]
        )
    )
    equipment_context = normalize_cell(row.get("Equipment")) or normalize_cell(inferred_equipment)
    equipment_key = normalize_key(equipment_context)

    epc_markers = [
        "foundation",
        "building",
        "structure",
        "structural",
        "road",
        "drainage",
        "underground",
        "plot plan",
        "layout",
        "cable raceway",
        "cable tray",
        "piping arrangement",
        "isometric",
        "support",
        "hazop",
        "sil",
        "study",
        "survey",
        "heat balance",
        "water balance",
        "control philosophy",
        "plant operation",
        "design criteria",
    ]
    vendor_markers = [
        "datasheet",
        "data sheet",
        "technical data",
        "performance curve",
        "performance data",
        "vendor",
        "shop drawing",
        "o m manual",
        "operation maintenance",
        "factory acceptance",
        "fat",
        "package",
        "equipment list",
    ]

    vendor_document_types = {
        "technical data sheet",
        "technical data sheet and drawing",
        "performance curve",
        "manual",
        "certificate",
        "quality dossier",
        "packing list",
        "technical specification",
    }
    doc_key = normalize_key(document_type)
    if doc_key in vendor_document_types and equipment_key and equipment_key not in normalize_key(" ".join(GENERIC_TITLE_EQUIPMENT)):
        if not any(marker in text for marker in ["foundation", "building structure", "road", "drainage", "underground", "civil works"]):
            return "Vendor"

    if any(marker in text for marker in epc_markers):
        return "EPC"
    if normalize_cell(row.get("Equipment")) and any(marker in text for marker in vendor_markers):
        return "Vendor"
    if "(v)" in normalize_cell(row.get("Title")).lower() or "（v）" in normalize_cell(row.get("Title")).lower():
        return "Vendor"
    if discipline in {"Civil/Structural", "Piping", "Process", "Electrical", "Instrumentation & Control"} and not normalize_cell(row.get("Equipment")):
        return "EPC"
    return "Vendor" if normalize_cell(row.get("Equipment")) else "EPC"


def infer_system(row: pd.Series, discipline: str) -> str:
    system = normalize_cell(row.get("System"))
    if system:
        return title_case_engineering(system)

    study = normalize_key(row.get("Study/Survey"))
    equipment = normalize_key(row.get("Equipment"))
    building = normalize_key(row.get("Building"))
    title = normalize_key(row.get("Title"))

    if any(term in study or term in title for term in ["load flow", "short circuit", "motor starting", "protection", "arc flash", "harmonic", "grid"]):
        return "Electrical Power System"
    if any(term in study or term in title for term in ["hazop", "hazid", "sil", "safety"]):
        return "Plant Safety System"
    if any(term in study or term in title for term in ["soil", "geotechnical", "survey", "hydrology", "flood"]):
        return "Civil / Site Infrastructure System"
    if any(term in title for term in ["heat balance", "performance", "thermal"]):
        return "Plant Performance System"
    if building:
        return "Building / Structure System"
    if equipment:
        return "Equipment Package System"
    if discipline == "General":
        return "Project General System"
    return "Plant General System"


def infer_sub_system(row: pd.Series) -> str:
    building = normalize_cell(row.get("Building"))
    if building:
        return title_case_engineering(building)
    others = normalize_cell(row.get("Others"))
    if others:
        return title_case_engineering(others)
    study = normalize_cell(row.get("Study/Survey"))
    if study:
        return title_case_engineering(study)
    return "General Area"


def infer_equipment(row: pd.Series, system: str, sub_system: str) -> str:
    equipment = normalize_cell(row.get("Equipment"))
    if equipment:
        return title_case_engineering(equipment)

    building = normalize_cell(row.get("Building"))
    if building:
        return f"{title_case_engineering(building)} Structure"

    study = normalize_cell(row.get("Study/Survey"))
    if study:
        return virtual_equipment_for_study(study)

    others = normalize_cell(row.get("Others"))
    if others:
        extracted = extract_equipment_from_text(others)
        return extracted or title_case_engineering(others)

    title_equipment = extract_equipment_from_text(row.get("Title"))
    if title_equipment:
        return title_equipment

    source_system = normalize_cell(row.get("System"))
    if source_system:
        return title_case_engineering(source_system)

    if "Electrical Power" in system:
        return "Electrical Network Model"
    if "Safety" in system:
        return "Plant Safety Model"
    if sub_system != "General Area":
        return sub_system
    return "Plant General"


def extract_equipment_from_text(value: object) -> str:
    text = normalize_cell(value)
    if not text:
        return ""
    patterns = [
        r"\bfor\s+(.+)$",
        r"\bFOR\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        subject = normalize_cell(match.group(1))
        subject = re.sub(r"^\[|\]$", "", subject)
        subject = re.sub(r"\s*\([^)]*plant area[^)]*\)\s*", " ", subject, flags=re.IGNORECASE)
        subject = normalize_cell(subject.strip(" _-[]"))
        expansions = {
            "CVP": "Condenser Vacuum Pump",
            "WBVP": "Water Box Vacuum Pump",
            "BOP": "Balance of Plant",
        }
        if subject.upper() in expansions:
            return expansions[subject.upper()]
        if len(subject) >= 3 and not is_non_document_title(subject):
            return title_case_engineering(subject)
    return ""


def virtual_equipment_for_study(study: str) -> str:
    key = normalize_key(study)
    if any(term in key for term in ["hazop", "hazid", "sil", "safety"]):
        return "Plant Safety Model"
    if any(term in key for term in ["load flow", "short circuit", "motor starting", "protection", "arc flash", "harmonic", "grid"]):
        return "Electrical Network Model"
    if any(term in key for term in ["soil", "geotechnical", "survey", "hydrology", "flood", "bathymetric", "metocean"]):
        return "Site Investigation Model"
    if "noise" in key:
        return "Plant Noise Model"
    if "emission" in key or "dispersion" in key:
        return "Air Emission Model"
    if "ram" in key:
        return "Plant Reliability Model"
    return f"{title_case_engineering(study)} Model"


def build_standard_title(equipment: str, document_type: str, source_title: object = "") -> str:
    equipment = normalize_cell(equipment) or "Plant General"
    document_type = normalize_cell(document_type) or "Document"
    if normalize_key(document_type) == "foundation drawing":
        base = equipment if "foundation" in normalize_key(equipment) else f"{equipment} Foundation"
        return normalize_cell(f"{base} Drawing")
    subject_title = build_subject_aware_title(equipment, document_type, source_title)
    if subject_title:
        return subject_title
    title = f"{equipment} {document_type}"
    title = re.sub(r"\b(Drawing) Drawing\b", "Drawing", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(Report) Report\b", "Report", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(Study) Study\b", "Study", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(Procedure) Procedure\b", "Procedure", title, flags=re.IGNORECASE)
    return normalize_cell(title)


def build_subject_aware_title(equipment: str, document_type: str, source_title: object) -> str:
    doc_key = normalize_key(document_type)
    if doc_key not in {"general arrangement drawing", "layout drawing", "technical data sheet", "design calculation"}:
        return ""
    subject = extract_source_subject(source_title)
    if not subject:
        return ""
    if doc_key == "general arrangement drawing":
        return normalize_cell(f"{equipment} {subject} Drawing")
    if doc_key == "layout drawing" and subject not in {"Plan View", "Section View"}:
        return normalize_cell(f"{equipment} {subject} Layout Drawing")
    if doc_key == "technical data sheet" and subject in {"Characteristic Curve", "Performance Curve"}:
        return normalize_cell(f"{equipment} {subject}")
    if doc_key == "design calculation":
        return normalize_cell(f"{equipment} {subject} Design Calculation")
    return ""


def extract_source_subject(source_title: object) -> str:
    text = normalize_cell(source_title)
    key = normalize_key(text)
    subject_rules = [
        ("Casing and Field Erection Arrangement", ["arrangement of casing field erection", "casing field erection"]),
        ("Inlet Duct Arrangement", ["arrangement of inlet duct", "inlet duct arrangement"]),
        ("Main Stack Field Erection Arrangement", ["arrangement of main stack field erection", "main stack field erection"]),
        ("Duct Burner System General Arrangement", ["general arrangement for duct burner system"]),
        ("Duct Burner System Detail Arrangement", ["detail arrangement for duct burner system"]),
        ("Duct Burner System Fuel Gas Skid Arrangement", ["fuel gas skid arrangement for duct burner system"]),
        ("Duct Burner System Cooling Air Skid Arrangement", ["cooling air skid arrangement for duct burner system"]),
        ("Pressure Part Arrangement", ["pressure part arrangement"]),
        ("Partition Plate and Gas Baffle Arrangement", ["partition plate gas baffle", "gas baffle arrangement"]),
        ("Chemical Dosing Shelter Portable Extinguisher Arrangement", ["portable extinguisher arrangement for chemical dosing shelter"]),
        ("Portable Extinguisher Arrangement", ["portable extinguisher arrangement"]),
        ("Catalyst Frame and Sealing Arrangement", ["catalyst frame sealing arrangement"]),
        ("Plan View", ["plan view"]),
        ("Section View", ["section a a", "section b b", "section c c"]),
        ("Roof Floor Plan", ["roof floor plan"]),
        ("Characteristic Curve", ["characteristic curve"]),
        ("Performance Curve", ["performance curve"]),
        ("Foundation and Loading Data", ["foundation and loading data", "foundation loading data"]),
    ]
    for subject, markers in subject_rules:
        if any(marker in key for marker in markers):
            return subject
    return ""


@dataclass(frozen=True)
class StandardKey:
    discipline: str
    scope_type: str
    standardized_title: str


def enrich_source_rows(source_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in source_df.iterrows():
        document_type = infer_document_type(row)
        discipline = infer_discipline(row, document_type)
        system = infer_system(row, discipline)
        sub_system = infer_sub_system(row)
        equipment = infer_equipment(row, system, sub_system)
        scope_type = infer_scope_type(row, discipline, document_type, equipment)
        standardized_title = build_standard_title(equipment, document_type, row.get("Title"))
        enriched = row.to_dict()
        enriched.update(
            {
                "_Discipline": discipline,
                "_Document Type": document_type,
                "_System": system,
                "_Sub-System": sub_system,
                "_Equipment": equipment,
                "_Scope Type": scope_type,
                "_Standardized Document Title": standardized_title,
            }
        )
        rows.append(enriched)
    return pd.DataFrame(rows)


def build_integrated_standard_mdl(enriched_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    groups: dict[StandardKey, list[pd.Series]] = {}
    for _, row in enriched_df.iterrows():
        key = StandardKey(
            discipline=row["_Discipline"],
            scope_type=row["_Scope Type"],
            standardized_title=row["_Standardized Document Title"],
        )
        groups.setdefault(key, []).append(row)

    standard_rows = []
    audit_rows = []
    for key in sorted(groups, key=lambda item: (item.discipline, item.scope_type, item.standardized_title)):
        source_rows = groups[key]
        representative = choose_representative_source(source_rows)
        validation_status, review_comment = initial_validation_status(key, source_rows)
        standard_no = len(standard_rows) + 1
        standard_rows.append(
            {
                "No": standard_no,
                "Discipline": key.discipline,
                "Document Type": representative["_Document Type"],
                "System": representative["_System"],
                "Sub-System": representative["_Sub-System"],
                "Sub-Sub System (Equipment)": representative["_Equipment"],
                "Standardized Document Title": key.standardized_title,
                "Scope Type": key.scope_type,
                "Source Projects": join_unique(row.get("Source Project") for row in source_rows),
                "Source Document Nos": join_unique(row.get("Document No") for row in source_rows),
                "Source Titles": join_unique(row.get("Title") for row in source_rows),
                "Evidence Type": "Source Title",
                "Validation Status": validation_status,
                "Review Comment": review_comment,
            }
        )
        for source in source_rows:
            audit_rows.append(
                {
                    "standard_no": standard_no,
                    "standardized_document_title": key.standardized_title,
                    "source_project": normalize_cell(source.get("Source Project")),
                    "source_file": normalize_cell(source.get("Source File")),
                    "sheet": normalize_cell(source.get("Sheet")),
                    "document_no": normalize_cell(source.get("Document No")),
                    "source_title": normalize_cell(source.get("Title")),
                    "source_equipment": normalize_cell(source.get("Equipment")),
                    "source_building": normalize_cell(source.get("Building")),
                    "source_system": normalize_cell(source.get("System")),
                    "source_study_survey": normalize_cell(source.get("Study/Survey")),
                    "source_others": normalize_cell(source.get("Others")),
                    "source_deliverable": normalize_cell(source.get("Deliverable")),
                }
            )
    standard_df = pd.DataFrame(standard_rows, columns=STANDARD_COLUMNS)
    audit_df = pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS)
    return consolidate_standard_and_audit(standard_df, audit_df)


def consolidate_standard_and_audit(standard_df: pd.DataFrame, audit_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if standard_df.empty:
        return standard_df, audit_df
    grouped_rows: list[dict[str, object]] = []
    old_to_new: dict[int, int] = {}
    for _, group in standard_df.groupby(["Standardized Document Title", "Scope Type"], sort=True, dropna=False):
        group = group.sort_values("No", kind="stable")
        representative = choose_standard_representative(group)
        new_no = len(grouped_rows) + 1
        for old_no in group["No"].astype(int).tolist():
            old_to_new[old_no] = new_no
        grouped_rows.append(
            {
                "No": new_no,
                "Discipline": choose_output_discipline(group),
                "Document Type": representative["Document Type"],
                "System": choose_context_value(group["System"]),
                "Sub-System": choose_context_value(group["Sub-System"]),
                "Sub-Sub System (Equipment)": choose_context_value(group["Sub-Sub System (Equipment)"]),
                "Standardized Document Title": representative["Standardized Document Title"],
                "Scope Type": representative["Scope Type"],
                "Source Projects": join_unique_tokens(group["Source Projects"]),
                "Source Document Nos": join_unique_tokens(group["Source Document Nos"]),
                "Source Titles": join_unique_tokens(group["Source Titles"]),
                "Evidence Type": "Source Title",
                "Validation Status": combine_validation_status(group["Validation Status"]),
                "Review Comment": join_unique_tokens(group["Review Comment"]),
            }
        )
    consolidated = pd.DataFrame(grouped_rows, columns=STANDARD_COLUMNS)
    remapped_audit = audit_df.copy()
    if not remapped_audit.empty:
        remapped_audit["standard_no"] = remapped_audit["standard_no"].astype(int).map(old_to_new)
        title_by_no = consolidated.set_index("No")["Standardized Document Title"].to_dict()
        remapped_audit["standardized_document_title"] = remapped_audit["standard_no"].map(title_by_no)
    consolidated, remapped_audit = disambiguate_scope_titles(consolidated, remapped_audit, "standard_no", "standardized_document_title")
    return collapse_exact_duplicate_titles(consolidated, remapped_audit, "standard_no", "standardized_document_title")


def consolidate_llm_standard_and_audit(standard_df: pd.DataFrame, audit_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if standard_df.empty:
        return standard_df, audit_df
    original = standard_df.copy()
    original["No"] = range(1, len(original) + 1)
    grouped_rows: list[dict[str, object]] = []
    old_to_new: dict[int, int] = {}
    for _, group in original.groupby(["Standardized Document Title", "Scope Type"], sort=True, dropna=False):
        group = group.sort_values("No", kind="stable")
        representative = choose_standard_representative(group)
        new_no = len(grouped_rows) + 1
        for old_no in group["No"].astype(int).tolist():
            old_to_new[old_no] = new_no
        grouped_rows.append(
            {
                "No": new_no,
                "Discipline": choose_output_discipline(group),
                "Document Type": representative["Document Type"],
                "System": choose_context_value(group["System"]),
                "Sub-System": choose_context_value(group["Sub-System"]),
                "Sub-Sub System (Equipment)": choose_context_value(group["Sub-Sub System (Equipment)"]),
                "Standardized Document Title": representative["Standardized Document Title"],
                "Scope Type": representative["Scope Type"],
                "Source Projects": join_unique_tokens(group["Source Projects"]),
                "Source Document Nos": join_unique_tokens(group["Source Document Nos"]),
                "Source Titles": join_unique_tokens(group["Source Titles"]),
                "Evidence Type": "Source Title",
                "Validation Status": combine_validation_status(group["Validation Status"]),
                "Review Comment": join_unique_tokens(group["Review Comment"]),
            }
        )
    consolidated = pd.DataFrame(grouped_rows, columns=STANDARD_COLUMNS)
    remapped_audit = audit_df.copy()
    if not remapped_audit.empty and "llm_standard_no" in remapped_audit.columns:
        remapped_audit["llm_standard_no"] = remapped_audit["llm_standard_no"].astype(int).map(old_to_new)
        title_by_no = consolidated.set_index("No")["Standardized Document Title"].to_dict()
        remapped_audit["llm_standardized_document_title"] = remapped_audit["llm_standard_no"].map(title_by_no)
    consolidated, remapped_audit = disambiguate_scope_titles(consolidated, remapped_audit, "llm_standard_no", "llm_standardized_document_title")
    return collapse_exact_duplicate_titles(consolidated, remapped_audit, "llm_standard_no", "llm_standardized_document_title")


def disambiguate_scope_titles(
    standard_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    audit_no_column: str,
    audit_title_column: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if standard_df.empty:
        return standard_df, audit_df
    updated = standard_df.copy()
    ambiguous_titles = {
        title
        for title, group in updated.groupby("Standardized Document Title", dropna=False)
        if {"Vendor", "EPC"} <= {normalize_cell(scope) for scope in group["Scope Type"]}
    }
    if not ambiguous_titles:
        return updated, audit_df
    for idx, row in updated[updated["Standardized Document Title"].isin(ambiguous_titles)].iterrows():
        updated.at[idx, "Standardized Document Title"] = scope_disambiguated_title(row)
    remapped_audit = audit_df.copy()
    if not remapped_audit.empty and audit_no_column in remapped_audit.columns:
        title_by_no = updated.set_index("No")["Standardized Document Title"].to_dict()
        remapped_audit[audit_title_column] = remapped_audit[audit_no_column].map(title_by_no)
    return updated, remapped_audit


def collapse_exact_duplicate_titles(
    standard_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    audit_no_column: str,
    audit_title_column: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if standard_df.empty:
        return standard_df, audit_df
    if not standard_df.groupby(["Standardized Document Title", "Scope Type"], dropna=False).size().gt(1).any():
        return standard_df, audit_df
    rows: list[dict[str, object]] = []
    old_to_new: dict[int, int] = {}
    for _, group in standard_df.groupby(["Standardized Document Title", "Scope Type"], sort=True, dropna=False):
        group = group.sort_values("No", kind="stable")
        representative = choose_standard_representative(group)
        new_no = len(rows) + 1
        for old_no in group["No"].astype(int).tolist():
            old_to_new[old_no] = new_no
        rows.append(
            {
                "No": new_no,
                "Discipline": choose_output_discipline(group),
                "Document Type": representative["Document Type"],
                "System": choose_context_value(group["System"]),
                "Sub-System": choose_context_value(group["Sub-System"]),
                "Sub-Sub System (Equipment)": choose_context_value(group["Sub-Sub System (Equipment)"]),
                "Standardized Document Title": representative["Standardized Document Title"],
                "Scope Type": representative["Scope Type"],
                "Source Projects": join_unique_tokens(group["Source Projects"]),
                "Source Document Nos": join_unique_tokens(group["Source Document Nos"]),
                "Source Titles": join_unique_tokens(group["Source Titles"]),
                "Evidence Type": "Source Title",
                "Validation Status": combine_validation_status(group["Validation Status"]),
                "Review Comment": join_unique_tokens(group["Review Comment"]),
            }
        )
    collapsed = pd.DataFrame(rows, columns=STANDARD_COLUMNS)
    remapped_audit = audit_df.copy()
    if not remapped_audit.empty and audit_no_column in remapped_audit.columns:
        remapped_audit[audit_no_column] = remapped_audit[audit_no_column].astype(int).map(old_to_new)
        title_by_no = collapsed.set_index("No")["Standardized Document Title"].to_dict()
        remapped_audit[audit_title_column] = remapped_audit[audit_no_column].map(title_by_no)
    return collapsed, remapped_audit


def sort_standard_and_audit(
    standard_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    audit_no_column: str,
    audit_title_column: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if standard_df.empty:
        return standard_df, audit_df

    sorted_df = standard_df.copy()
    sorted_df["Source Projects"] = sorted_df["Source Projects"].map(sort_joined_projects)
    sorted_df["_discipline_order"] = sorted_df["Discipline"].map(order_index(DISCIPLINE_ORDER))
    sorted_df["_scope_order"] = sorted_df["Scope Type"].map(order_index(SCOPE_ORDER))
    sorted_df["_system_key"] = sorted_df["System"].map(normalize_key)
    sorted_df["_sub_system_key"] = sorted_df["Sub-System"].map(normalize_key)
    sorted_df["_equipment_key"] = sorted_df["Sub-Sub System (Equipment)"].map(normalize_key)
    sorted_df["_document_type_key"] = sorted_df["Document Type"].map(normalize_key)
    sorted_df["_title_key"] = sorted_df["Standardized Document Title"].map(normalize_key)
    sorted_df = sorted_df.sort_values(
        [
            "_discipline_order",
            "_scope_order",
            "_system_key",
            "_sub_system_key",
            "_equipment_key",
            "_document_type_key",
            "_title_key",
        ],
        kind="stable",
    )
    old_to_new = {int(old_no): index + 1 for index, old_no in enumerate(sorted_df["No"].astype(int).tolist())}
    sorted_df["No"] = range(1, len(sorted_df) + 1)
    sorted_df = sorted_df[STANDARD_COLUMNS].reset_index(drop=True)

    remapped_audit = audit_df.copy()
    if not remapped_audit.empty and audit_no_column in remapped_audit.columns:
        remapped_audit[audit_no_column] = remapped_audit[audit_no_column].astype(int).map(old_to_new)
        title_by_no = sorted_df.set_index("No")["Standardized Document Title"].to_dict()
        remapped_audit[audit_title_column] = remapped_audit[audit_no_column].map(title_by_no)
        sort_columns = [audit_no_column]
        if "source_project" in remapped_audit.columns:
            remapped_audit["_source_project_order"] = remapped_audit["source_project"].map(order_index(PROJECT_ORDER))
            sort_columns.append("_source_project_order")
        if "source_title" in remapped_audit.columns:
            remapped_audit["_source_title_key"] = remapped_audit["source_title"].map(normalize_key)
            sort_columns.append("_source_title_key")
        remapped_audit = remapped_audit.sort_values(sort_columns, kind="stable")
        remapped_audit = remapped_audit[[column for column in remapped_audit.columns if not column.startswith("_")]]
    return sorted_df, remapped_audit


def order_index(order: list[str]):
    mapping = {value: index for index, value in enumerate(order)}

    def _index(value: object) -> int:
        return mapping.get(normalize_cell(value), len(mapping))

    return _index


def scope_disambiguated_title(row: pd.Series) -> str:
    title = normalize_cell(row.get("Standardized Document Title"))
    document_type = normalize_cell(row.get("Document Type"))
    equipment = normalize_cell(row.get("Sub-Sub System (Equipment)"))
    scope = normalize_cell(row.get("Scope Type"))
    discipline = normalize_cell(row.get("Discipline"))
    if scope == "Vendor":
        qualifier = "Vendor Package"
    elif discipline == "Piping":
        qualifier = "EPC Piping Interface"
    elif discipline == "Civil/Structural":
        qualifier = "EPC Civil/Structural"
    elif discipline == "Electrical":
        qualifier = "EPC Electrical Interface"
    elif discipline == "Instrumentation & Control":
        qualifier = "EPC I&C Interface"
    elif discipline == "Process":
        qualifier = "EPC Process Interface"
    else:
        qualifier = "EPC Integration"
    if document_type and title.endswith(document_type):
        base = normalize_cell(title[: -len(document_type)])
        return normalize_cell(f"{base} {qualifier} {document_type}")
    if equipment and title.startswith(equipment):
        return normalize_cell(title.replace(equipment, f"{equipment} {qualifier}", 1))
    return normalize_cell(f"{qualifier} {title}")


def choose_standard_representative(group: pd.DataFrame) -> pd.Series:
    def score(row: pd.Series) -> tuple[int, int, str]:
        value = 0
        if normalize_cell(row.get("Validation Status")) == "OK":
            value += 20
        if normalize_cell(row.get("Sub-Sub System (Equipment)")) not in GENERIC_TITLE_EQUIPMENT:
            value += 10
        if normalize_cell(row.get("System")) not in {"Plant General System", "Project General System"}:
            value += 5
        return (-value, int(row.get("No", 0)), normalize_cell(row.get("Standardized Document Title")))

    return group.iloc[min(range(len(group)), key=lambda idx: score(group.iloc[idx]))]


def choose_output_discipline(group: pd.DataFrame) -> str:
    title_key = normalize_key(group["Standardized Document Title"].iloc[0])
    doc_key = normalize_key(group["Document Type"].iloc[0])
    if any(term in title_key or term in doc_key for term in ["foundation", "building", "structure", "civil", "road", "drainage"]):
        return "Civil/Structural"
    if any(term in title_key or term in doc_key for term in ["piping", "pipe", "isometric", "p id"]):
        return "Piping"
    if any(term in title_key or term in doc_key for term in ["instrument", "control", "dcs", "plc", "transmitter", "analyzer"]):
        return "Instrumentation & Control"
    if any(term in title_key or term in doc_key for term in ["cable", "switchgear", "transformer", "electrical", "grounding", "earthing", "lighting", "battery", "ups"]):
        return "Electrical"
    return majority_value(group["Discipline"])


def choose_context_value(values: Iterable[object]) -> str:
    non_generic = [normalize_cell(value) for value in values if normalize_cell(value) not in GENERIC_TITLE_EQUIPMENT]
    return majority_value(non_generic) if non_generic else majority_value(values)


def combine_validation_status(values: Iterable[object]) -> str:
    statuses: list[str] = []
    for value in values:
        for part in normalize_cell(value).split(";"):
            text = normalize_cell(part)
            if text and text != "OK":
                statuses.append(text)
    if not statuses:
        return "OK"
    return "; ".join(dict.fromkeys(statuses))


def choose_representative_source(source_rows: list[pd.Series]) -> pd.Series:
    def score(row: pd.Series) -> tuple[int, int, str]:
        title = normalize_key(row.get("Title"))
        value = 0
        if normalize_cell(row.get("Equipment")):
            value += 20
        if normalize_cell(row.get("System")):
            value += 8
        if normalize_cell(row.get("Building")):
            value += 5
        if any(term in title for term in ["general", "technical", "design", "system"]):
            value += 3
        return (-value, len(title), title)

    return sorted(source_rows, key=score)[0]


def llm_merge_prompt() -> str:
    return """You are a Combined Cycle Power Plant (CCPP) document control expert.

Merge Standard MDL candidate rows only when they represent the same engineering deliverable.

Core rules:
- Do not target any row count. Never merge or split to satisfy a quantity.
- Merge only by engineering meaning.
- Keep different equipment separate.
- Keep different document purpose separate.
- Same package and same document type is not enough to merge.
- Keep different drawing/calculation subjects separate even when they belong to the same package.
- Do not merge general arrangement, detail arrangement, inlet duct arrangement, main stack arrangement, skid arrangement, casing arrangement, pressure part arrangement, and fire extinguisher arrangement into one item unless the input titles clearly mean the exact same deliverable.
- Do not merge different sub-equipment, area, train, block, building, foundation, system model, or interface subjects into one item.
- If the merge reason would be only "same package", "similar document type", or "both are arrangements", keep the rows separate.
- Never mix Vendor and EPC scope in one output item.
- Standardized Document Title may be rewritten, but it must remain concise and document-control friendly.
- Use the naming pattern: [Equipment Name] + [Document Type].
- Do not create generic titles such as "Drawing", "Calculation", "Foundation Drawing", or "Building Drawing".
- Return every input candidate row number exactly once in source_standard_nos.
- Do not cite or create source titles. Use only source_standard_nos to reference input.
"""


def llm_candidate_payload(df: pd.DataFrame) -> list[dict[str, object]]:
    payload = []
    for _, row in df.iterrows():
        payload.append(
            {
                "standard_no": int(row["No"]),
                "discipline": normalize_cell(row["Discipline"]),
                "document_type": normalize_cell(row["Document Type"]),
                "system": normalize_cell(row["System"]),
                "sub_system": normalize_cell(row["Sub-System"]),
                "equipment": normalize_cell(row["Sub-Sub System (Equipment)"]),
                "standardized_document_title": normalize_cell(row["Standardized Document Title"]),
                "scope_type": normalize_cell(row["Scope Type"]),
                "source_projects": normalize_cell(row["Source Projects"]),
                "source_titles": normalize_cell(row["Source Titles"])[:1200],
            }
        )
    return payload


def run_llm_merge_batch(client: AzureOpenAI, batch_df: pd.DataFrame) -> LLMStandardGroupList:
    discipline = normalize_cell(batch_df["Discipline"].iloc[0])
    scope_type = normalize_cell(batch_df["Scope Type"].iloc[0])
    document_type = normalize_cell(batch_df["Document Type"].iloc[0])
    user_message = (
        "Merge the following Standard MDL candidate rows.\n"
        f"GROUP_CONTEXT: Discipline={discipline}, Scope Type={scope_type}, Document Type={document_type}\n"
        "Return structured output only.\n\n"
        f"CANDIDATES:\n{json.dumps(llm_candidate_payload(batch_df), ensure_ascii=False, indent=2)}"
    )
    try:
        response = client.chat.completions.parse(
            model=AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": llm_merge_prompt()},
                {"role": "user", "content": user_message},
            ],
            response_format=LLMStandardGroupList,
            max_completion_tokens=16000,
        )
    except AttributeError:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": llm_merge_prompt()},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=16000,
        )
    return parse_structured_response(response, LLMStandardGroupList)


def iter_llm_batches(standard_df: pd.DataFrame, pilot: bool, batch_size: int) -> Iterable[pd.DataFrame]:
    grouped = standard_df.groupby(["Discipline", "Scope Type", "Document Type"], sort=True)
    for group_key, group_df in grouped:
        if pilot and group_key not in PILOT_GROUPS:
            continue
        if len(group_df) <= 1:
            continue
        ordered = group_df.sort_values(
            ["Sub-Sub System (Equipment)", "Standardized Document Title", "No"],
            kind="stable",
        ).reset_index(drop=True)
        for start in range(0, len(ordered), batch_size):
            yield ordered.iloc[start:start + batch_size].reset_index(drop=True)


def llm_eligible_standard_nos(standard_df: pd.DataFrame, pilot: bool) -> set[int]:
    eligible: set[int] = set()
    grouped = standard_df.groupby(["Discipline", "Scope Type", "Document Type"], sort=True)
    for group_key, group_df in grouped:
        if pilot and group_key not in PILOT_GROUPS:
            continue
        eligible.update(group_df["No"].astype(int).tolist())
    return eligible


def build_llm_refined_mdl(
    standard_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    pilot: bool,
    batch_size: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    client = build_client()
    standard_by_no = {int(row["No"]): row for _, row in standard_df.iterrows()}
    audit_by_no = {int(no): rows for no, rows in audit_df.groupby("standard_no")}
    output_rows: list[dict[str, object]] = []
    merge_audit_rows: list[dict[str, object]] = []
    rejection_rows: list[dict[str, str]] = []
    assigned: set[int] = set()
    eligible_nos = llm_eligible_standard_nos(standard_df, pilot=pilot)
    batches = list(iter_llm_batches(standard_df, pilot=pilot, batch_size=batch_size))
    print(f"[STANDARD-MDL][LLM] batches: {len(batches)}", flush=True)

    for batch_index, batch_df in enumerate(batches, start=1):
        if batch_df.empty:
            continue
        group_label = (
            normalize_cell(batch_df["Discipline"].iloc[0]),
            normalize_cell(batch_df["Scope Type"].iloc[0]),
            normalize_cell(batch_df["Document Type"].iloc[0]),
        )
        print(f"[STANDARD-MDL][LLM] batch {batch_index}/{len(batches)} {group_label} rows={len(batch_df)}", flush=True)
        result = run_llm_merge_batch(client, batch_df)
        valid_nos = set(batch_df["No"].astype(int).tolist())
        for item in result.items:
            raw_payload = item.model_dump()
            refs = [int(no) for no in item.source_standard_nos if int(no) in valid_nos]
            invalid_refs = [int(no) for no in item.source_standard_nos if int(no) not in valid_nos]
            if invalid_refs:
                rejection_rows.append(
                    {
                        "source_project": "",
                        "source_file": "",
                        "sheet": "",
                        "document_no": "",
                        "source_title": "",
                        "reason": f"llm_invalid_standard_no:{invalid_refs}",
                        "raw_payload": json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
                    }
                )
            refs = [no for no in refs if no not in assigned]
            if not refs:
                rejection_rows.append(
                    {
                        "source_project": "",
                        "source_file": "",
                        "sheet": "",
                        "document_no": "",
                        "source_title": "",
                        "reason": "llm_group_without_unassigned_valid_refs",
                        "raw_payload": json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
                    }
                )
                continue
            refs, split_refs, split_reason = enforce_conservative_merge_refs(refs, standard_by_no)
            for split_no in split_refs:
                source = standard_by_no[split_no]
                output_rows.append(copy_rule_row_for_llm_output(source, split_reason))
                assigned.add(split_no)
                for _, audit_row in audit_by_no.get(split_no, pd.DataFrame(columns=AUDIT_COLUMNS)).iterrows():
                    payload = audit_row.to_dict()
                    payload["llm_batch"] = batch_index
                    payload["llm_standard_no"] = len(output_rows)
                    payload["llm_standardized_document_title"] = source["Standardized Document Title"]
                    payload["source_rule_standard_no"] = split_no
                    payload["llm_merge_reason"] = split_reason
                    merge_audit_rows.append(payload)
                rejection_rows.append(
                    {
                        "source_project": "",
                        "source_file": "",
                        "sheet": "",
                        "document_no": "",
                        "source_title": normalize_cell(source["Standardized Document Title"]),
                        "reason": "llm_merge_split_by_guardrail",
                        "raw_payload": json.dumps({"standard_no": split_no, "original_group": raw_payload}, ensure_ascii=False, sort_keys=True),
                    }
                )
            if not refs:
                continue
            assigned.update(refs)
            source_standard_rows = [standard_by_no[no] for no in refs]
            row = llm_output_row(item, source_standard_rows, refs)
            output_rows.append(row)
            for no in refs:
                for _, audit_row in audit_by_no.get(no, pd.DataFrame(columns=AUDIT_COLUMNS)).iterrows():
                    payload = audit_row.to_dict()
                    payload["llm_batch"] = batch_index
                    payload["llm_standard_no"] = len(output_rows)
                    payload["llm_standardized_document_title"] = row["Standardized Document Title"]
                    payload["source_rule_standard_no"] = no
                    payload["llm_merge_reason"] = normalize_cell(item.merge_reason)
                    merge_audit_rows.append(payload)

        missing_nos = [int(no) for no in batch_df["No"].tolist() if int(no) not in assigned]
        for no in missing_nos:
            source = standard_by_no[no]
            output_rows.append(copy_rule_row_for_llm_output(source))
            assigned.add(no)
            for _, audit_row in audit_by_no.get(no, pd.DataFrame(columns=AUDIT_COLUMNS)).iterrows():
                payload = audit_row.to_dict()
                payload["llm_batch"] = batch_index
                payload["llm_standard_no"] = len(output_rows)
                payload["llm_standardized_document_title"] = source["Standardized Document Title"]
                payload["source_rule_standard_no"] = no
                payload["llm_merge_reason"] = "Fallback: LLM did not assign this candidate row."
                merge_audit_rows.append(payload)
            rejection_rows.append(
                {
                    "source_project": "",
                    "source_file": "",
                    "sheet": "",
                    "document_no": "",
                    "source_title": normalize_cell(source["Standardized Document Title"]),
                    "reason": "llm_missing_assignment_fallback_used",
                    "raw_payload": json.dumps({"standard_no": no}, ensure_ascii=False, sort_keys=True),
                }
            )

    skipped_singletons = sorted(no for no in eligible_nos if no not in assigned)
    for no in skipped_singletons:
        source = standard_by_no[no]
        output_rows.append(copy_rule_row_for_llm_output(source, "Copied without LLM call because no same-group merge candidate exists."))
        assigned.add(no)
        for _, audit_row in audit_by_no.get(no, pd.DataFrame(columns=AUDIT_COLUMNS)).iterrows():
            payload = audit_row.to_dict()
            payload["llm_batch"] = 0
            payload["llm_standard_no"] = len(output_rows)
            payload["llm_standardized_document_title"] = source["Standardized Document Title"]
            payload["source_rule_standard_no"] = no
            payload["llm_merge_reason"] = "Singleton group copied without LLM call."
            merge_audit_rows.append(payload)

    output_df = pd.DataFrame(output_rows, columns=STANDARD_COLUMNS)
    if not output_df.empty:
        output_df["No"] = range(1, len(output_df) + 1)
    merge_audit_df = pd.DataFrame(merge_audit_rows)
    output_df, merge_audit_df = consolidate_llm_standard_and_audit(output_df, merge_audit_df)
    rejection_df = pd.DataFrame(rejection_rows, columns=REJECTION_COLUMNS)
    return output_df, merge_audit_df, rejection_df


def enforce_conservative_merge_refs(refs: list[int], standard_by_no: dict[int, pd.Series]) -> tuple[list[int], list[int], str]:
    if len(refs) <= 1:
        return refs, [], ""
    rows = [standard_by_no[no] for no in refs]
    strict_keys = [strict_merge_key(row) for row in rows]
    majority_key = majority_value(strict_keys)
    keep = [no for no, key in zip(refs, strict_keys) if key == majority_key]
    split = [no for no, key in zip(refs, strict_keys) if key != majority_key]
    reason = "Guardrail: kept separate because equipment, system, sub-system, document type, scope, or title subject differs."
    return keep, split, reason


def strict_merge_key(row: pd.Series) -> str:
    title = normalize_cell(row.get("Standardized Document Title"))
    equipment = normalize_cell(row.get("Sub-Sub System (Equipment)"))
    document_type = normalize_cell(row.get("Document Type"))
    scope_type = normalize_cell(row.get("Scope Type"))
    system = normalize_cell(row.get("System"))
    sub_system = normalize_cell(row.get("Sub-System"))
    subject = title_subject_key(title, equipment, document_type)
    return "||".join(normalize_key(value) for value in [scope_type, document_type, system, sub_system, equipment, subject])


def title_subject_key(title: object, equipment: object, document_type: object) -> str:
    text = normalize_cell(title)
    equipment_text = normalize_cell(equipment)
    document_type_text = normalize_cell(document_type)
    for part in [equipment_text, document_type_text]:
        if part:
            text = re.sub(re.escape(part), " ", text, flags=re.IGNORECASE)
    text = normalize_key(text)
    if not text:
        return "base"
    subject_markers = [
        "general arrangement",
        "detail arrangement",
        "inlet duct",
        "main stack",
        "duct burner",
        "fuel gas skid",
        "cooling air skid",
        "casing",
        "field erection",
        "pressure part",
        "partition plate",
        "gas baffle",
        "portable extinguisher",
        "characteristic curve",
        "performance curve",
        "foundation layout",
        "foundation reinforcement",
        "foundation design",
    ]
    matched = [marker for marker in subject_markers if marker in text]
    return " ".join(matched) if matched else text


def llm_output_row(item: LLMStandardGroup, source_standard_rows: list[pd.Series], refs: list[int]) -> dict[str, object]:
    title = normalize_cell(item.standardized_document_title)
    if not title:
        title = build_standard_title(item.equipment, item.document_type)
    scope_type = normalize_cell(item.scope_type)
    if scope_type not in {"Vendor", "EPC"}:
        scope_type = majority_value(row["Scope Type"] for row in source_standard_rows)
    return {
        "No": 0,
        "Discipline": normalize_cell(item.discipline) or majority_value(row["Discipline"] for row in source_standard_rows),
        "Document Type": normalize_cell(item.document_type) or majority_value(row["Document Type"] for row in source_standard_rows),
        "System": normalize_cell(item.system) or majority_value(row["System"] for row in source_standard_rows),
        "Sub-System": normalize_cell(item.sub_system) or majority_value(row["Sub-System"] for row in source_standard_rows),
        "Sub-Sub System (Equipment)": normalize_cell(item.equipment) or majority_value(row["Sub-Sub System (Equipment)"] for row in source_standard_rows),
        "Standardized Document Title": title,
        "Scope Type": scope_type,
        "Source Projects": join_unique_tokens(row["Source Projects"] for row in source_standard_rows),
        "Source Document Nos": join_unique_tokens(row["Source Document Nos"] for row in source_standard_rows),
        "Source Titles": join_unique_tokens(row["Source Titles"] for row in source_standard_rows),
        "Evidence Type": "Source Title",
        "Validation Status": "OK",
        "Review Comment": f"LLM merged rule rows: {', '.join(str(no) for no in refs)}. {normalize_cell(item.merge_reason)}",
    }


def copy_rule_row_for_llm_output(source: pd.Series, comment: str = "Fallback copied from rule-based Standard MDL.") -> dict[str, object]:
    row = {column: source[column] for column in STANDARD_COLUMNS}
    row["No"] = 0
    row["Review Comment"] = join_unique([row.get("Review Comment"), comment])
    return row


def majority_value(values: Iterable[object]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        text = normalize_cell(value)
        if text:
            counts[text] = counts.get(text, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def initial_validation_status(key: StandardKey, source_rows: list[pd.Series]) -> tuple[str, str]:
    statuses = []
    comments = []
    title_key = normalize_key(key.standardized_title)

    equipment_values = {normalize_cell(row.get("_Equipment")) for row in source_rows}
    if equipment_values <= GENERIC_TITLE_EQUIPMENT:
        statuses.append("Generic Title")
        comments.append("Standard title has weak equipment/object context.")

    if key.scope_type == "Vendor" and any(term in title_key for term in ["foundation", "building", "cable raceway", "layout", "piping support", "road", "drainage", "underground"]):
        statuses.append("Scope Mixed")
        comments.append("Vendor scope row contains EPC/infrastructure markers.")

    if (
        key.scope_type == "EPC"
        and equipment_values - GENERIC_TITLE_EQUIPMENT
        and any(term in title_key for term in ["datasheet", "data sheet", "performance curve", "vendor ga", "shop drawing"])
    ):
        statuses.append("Scope Mixed")
        comments.append("EPC scope row contains vendor deliverable markers.")

    if len(source_rows) > 8:
        statuses.append("Possible Over-Merge")
        comments.append(f"{len(source_rows)} source rows were grouped into one standard item.")

    if not statuses:
        return "OK", ""
    return "; ".join(dict.fromkeys(statuses)), " | ".join(dict.fromkeys(comments))


def build_validation_report(standard_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    rows.extend(validate_standard_rows(standard_df))
    rows.extend(validate_non_document_standard_titles(standard_df))
    rows.extend(validate_duplicate_standard_titles(standard_df))
    rows.extend(validate_vendor_epc_ambiguity(standard_df))
    rows.extend(validate_foundation_gaps(standard_df))
    rows.extend(validate_building_structure_gaps(standard_df))
    rows.extend(validate_study_gaps(standard_df))
    return pd.DataFrame(rows, columns=VALIDATION_COLUMNS)


def build_expert_augmented_mdl(
    standard_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    batch_size: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create a reviewable LLM expert supplement without Copilot input."""
    base_df = standard_df.copy()
    expert_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    rejection_rows: list[dict[str, str]] = []

    existing_keys = {
        (
            normalize_key(row.get("Standardized Document Title")),
            normalize_cell(row.get("Scope Type")),
        )
        for _, row in base_df.iterrows()
    }

    for _, row in base_df.iterrows():
        copied = row.to_dict()
        copied["Source Standard Nos"] = normalize_cell(row.get("No"))
        copied["Review Status"] = "Approved Source-Grounded"
        copied["Augmentation Reason"] = "Existing source-grounded Standard MDL row."
        expert_rows.append(copied)

    for candidate in source_inferred_candidates_from_standard(base_df):
        add_expert_candidate(candidate, existing_keys, expert_rows, audit_rows)

    client = build_client()
    batches = list(iter_expert_generation_batches(base_df, batch_size=batch_size))
    print(f"[STANDARD-MDL][EXPERT-PROMPT] batches: {len(batches)}", flush=True)
    for batch_index, batch_df in enumerate(batches, start=1):
        if batch_df.empty:
            continue
        group_label = (
            normalize_cell(batch_df["Discipline"].iloc[0]),
            normalize_cell(batch_df["Scope Type"].iloc[0]),
        )
        print(f"[STANDARD-MDL][EXPERT-PROMPT] batch {batch_index}/{len(batches)} {group_label} rows={len(batch_df)}", flush=True)
        try:
            result = run_expert_generation_batch(client, batch_df)
        except Exception as exc:  # Keep long runs reviewable even if one LLM batch fails.
            rejection_rows.append(
                {
                    "source_project": "",
                    "source_file": "",
                    "sheet": "",
                    "document_no": "",
                    "source_title": f"batch:{batch_index}",
                    "reason": f"expert_prompt_batch_failed:{type(exc).__name__}",
                    "raw_payload": json.dumps(
                        {
                            "batch_index": batch_index,
                            "group": group_label,
                            "standard_nos": batch_df["No"].astype(int).tolist(),
                            "error": str(exc)[:2000],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
            continue
        valid_nos = set(batch_df["No"].astype(int).tolist())
        for item in result.items:
            raw_payload = item.model_dump()
            refs = [int(no) for no in item.source_standard_nos if int(no) in valid_nos]
            if not refs:
                rejection_rows.append(
                    {
                        "source_project": "",
                        "source_file": "",
                        "sheet": "",
                        "document_no": "",
                        "source_title": normalize_cell(item.standardized_document_title),
                        "reason": "expert_prompt_missing_valid_source_standard_no",
                        "raw_payload": json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
                    }
                )
                continue
            source_rows = [base_df.loc[base_df["No"].astype(int).eq(no)].iloc[0] for no in refs]
            candidate = expert_item_to_candidate(item, source_rows, refs)
            add_expert_candidate(candidate, existing_keys, expert_rows, audit_rows)

    output_df = pd.DataFrame(expert_rows, columns=EXPERT_COLUMNS)
    if not output_df.empty:
        output_df["No"] = range(1, len(output_df) + 1)
    output_df, audit_df = consolidate_expert_augmented_output(output_df, pd.DataFrame(audit_rows))
    validation_report = build_expert_augmentation_validation(output_df)
    if rejection_rows:
        rejection_df = pd.DataFrame(rejection_rows, columns=REJECTION_COLUMNS)
        validation_report = pd.concat(
            [
                validation_report,
                expert_prompt_rejections_to_validation(rejection_df),
            ],
            ignore_index=True,
        )
    return output_df, audit_df, validation_report


def expert_item_to_candidate(item: ExpertGeneratedItem, source_rows: list[pd.Series], refs: list[int]) -> dict[str, object]:
    evidence_type = normalize_cell(item.evidence_type)
    if evidence_type not in {"Source-Inferred", "Expert-Inferred"}:
        evidence_type = "Expert-Inferred"
    return {
        "Discipline": normalize_cell(item.discipline) or majority_value(row["Discipline"] for row in source_rows),
        "Document Type": normalize_cell(item.document_type) or majority_value(row["Document Type"] for row in source_rows),
        "System": normalize_cell(item.system) or majority_value(row["System"] for row in source_rows),
        "Sub-System": normalize_cell(item.sub_system) or majority_value(row["Sub-System"] for row in source_rows),
        "Sub-Sub System (Equipment)": normalize_cell(item.equipment) or majority_value(row["Sub-Sub System (Equipment)"] for row in source_rows),
        "Standardized Document Title": normalize_cell(item.standardized_document_title),
        "Scope Type": normalize_cell(item.scope_type) or majority_value(row["Scope Type"] for row in source_rows),
        "Evidence Type": evidence_type,
        "Review Comment": f"LLM expert-generated from source Standard MDL rows: {', '.join(str(no) for no in refs)}.",
        "Augmentation Reason": normalize_cell(item.generation_reason),
        "Source Basis": f"llm_expert_prompt:{','.join(str(no) for no in refs)}",
        "Source Standard Nos": join_unique(refs),
        "Source Projects": join_unique_tokens(row["Source Projects"] for row in source_rows),
        "Source Document Nos": join_unique_tokens(row["Source Document Nos"] for row in source_rows),
        "Source Titles": join_unique_tokens(row["Source Titles"] for row in source_rows),
    }


def expert_prompt_rejections_to_validation(rejection_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in rejection_df.iterrows():
        rows.append(
            {
                "validation_type": "Expert Prompt Rejection",
                "severity": "review",
                "discipline": "",
                "scope_type": "",
                "system": "",
                "sub_system": "",
                "equipment": "",
                "document_type": "",
                "standardized_document_title": normalize_cell(row.get("source_title")),
                "reason": normalize_cell(row.get("reason")),
                "recommended_action": "Review prompt output; rejected rows were not included in the Standard MDL draft.",
            }
        )
    return pd.DataFrame(rows, columns=VALIDATION_COLUMNS)


def add_expert_candidate(
    candidate: dict[str, object],
    existing_keys: set[tuple[str, str]],
    expert_rows: list[dict[str, object]],
    audit_rows: list[dict[str, object]],
) -> None:
    title = normalize_cell(candidate.get("Standardized Document Title"))
    scope_type = normalize_cell(candidate.get("Scope Type"))
    if not title or scope_type not in {"Vendor", "EPC"}:
        return
    key = (normalize_key(title), scope_type)
    if key in existing_keys:
        return
    existing_keys.add(key)
    row = {column: normalize_cell(candidate.get(column)) for column in STANDARD_COLUMNS}
    row["No"] = 0
    row["Source Projects"] = normalize_cell(candidate.get("Source Projects"))
    row["Source Document Nos"] = normalize_cell(candidate.get("Source Document Nos")) or EXPERT_SOURCE_DOCUMENT_NO
    row["Source Titles"] = normalize_cell(candidate.get("Source Titles"))
    row["Source Standard Nos"] = normalize_cell(candidate.get("Source Standard Nos"))
    evidence_type = normalize_cell(candidate.get("Evidence Type")) or "Expert-Inferred"
    if evidence_type not in {"Source-Inferred", "Expert-Inferred"}:
        evidence_type = "Expert-Inferred"
    row["Evidence Type"] = evidence_type
    row["Validation Status"] = "Needs Doosan Review"
    row["Review Comment"] = normalize_cell(candidate.get("Review Comment")) or "Expert-inferred candidate generated from CCPP standard MDL rules."
    row["Review Status"] = "Needs Doosan Review"
    row["Augmentation Reason"] = normalize_cell(candidate.get("Augmentation Reason")) or row["Review Comment"]
    expert_rows.append(row)
    audit_rows.append(
        {
            "standardized_document_title": title,
            "scope_type": scope_type,
            "evidence_type": evidence_type,
            "source_basis": normalize_cell(candidate.get("Source Basis")),
            "source_projects": row["Source Projects"],
            "source_document_nos": row["Source Document Nos"],
            "source_standard_nos": row["Source Standard Nos"],
            "source_titles": row["Source Titles"],
            "augmentation_reason": row["Augmentation Reason"],
        }
    )


def source_inferred_candidates_from_standard(standard_df: pd.DataFrame) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    split_rules = [
        (
            "Technical Data Sheet and Drawing",
            [
                ("Technical Data Sheet", "Technical Data Sheet"),
                ("General Arrangement Drawing", "General Arrangement Drawing"),
            ],
        ),
        (
            "Data Sheet and Drawing",
            [
                ("Technical Data Sheet", "Technical Data Sheet"),
                ("General Arrangement Drawing", "General Arrangement Drawing"),
            ],
        ),
    ]
    for _, row in standard_df.iterrows():
        document_type = normalize_cell(row.get("Document Type"))
        equipment = normalize_cell(row.get("Sub-Sub System (Equipment)"))
        if not equipment or equipment in GENERIC_TITLE_EQUIPMENT:
            continue
        for combined_type, parts in split_rules:
            if normalize_key(document_type) != normalize_key(combined_type):
                continue
            for output_type, title_type in parts:
                candidates.append(
                    {
                        "Discipline": normalize_cell(row.get("Discipline")),
                        "Document Type": output_type,
                        "System": normalize_cell(row.get("System")),
                        "Sub-System": normalize_cell(row.get("Sub-System")),
                        "Sub-Sub System (Equipment)": equipment,
                        "Standardized Document Title": f"{equipment} {title_type}",
                        "Scope Type": normalize_cell(row.get("Scope Type")),
                        "Evidence Type": "Source-Inferred",
                        "Review Comment": f"Split from source-grounded combined deliverable '{document_type}'.",
                        "Augmentation Reason": "Source title represents a combined deliverable; split candidate provided for review.",
                        "Source Basis": f"combined_deliverable:{normalize_cell(row.get('No'))}",
                        "Source Standard Nos": normalize_cell(row.get("No")),
                        "Source Projects": normalize_cell(row.get("Source Projects")),
                        "Source Document Nos": normalize_cell(row.get("Source Document Nos")),
                        "Source Titles": normalize_cell(row.get("Source Titles")),
                    }
                )
    return candidates


def expert_generation_prompt() -> str:
    return """You are a Combined Cycle Power Plant (CCPP) design and document-control expert.

Create an integrated Standard MDL draft supplement from the given source-grounded Standard MDL rows.

Use the rows as reference evidence, not as a hard title dictionary. You may rewrite standardized document titles and may add expert-inferred deliverables when the source rows establish the relevant package, system, equipment, building, study, or discipline context.

Hard constraints:
- Do not use or assume any Copilot result.
- Do not target any row count.
- Do not output C/E/I classification, confidence, contract extracts, or ITB matching fields.
- Keep Vendor and EPC scope fully separated.
- Keep the four-level structure: System, Sub-System, Equipment, Document Type.
- Use document-control-friendly titles in the pattern: [Equipment Name] + [Document Type].
- Do not create generic titles such as Drawing, Calculation, Report, Foundation Drawing, or Building Drawing.
- Do not merge Vendor detail documents with EPC integration/civil/system documents.
- Do not over-split components only to increase quantity. Generate component-level rows only when they are normal CCPP package deliverables supported by the source context.
- Return only the highest-value supplement rows for the batch, up to 12 items. This is a response-size cap, not a target quantity.
- Every output row must cite at least one input source_standard_no from this batch.

Evidence type policy:
- Source-Inferred: the source row clearly contains a combined/implicit deliverable that can be split or standardized using the source title meaning.
- Expert-Inferred: the source row establishes package/system/equipment context, and CCPP engineering knowledge indicates the deliverable is normally needed.

Scope policy:
- Vendor Scope: equipment/package vendor documents such as data sheets, vendor GA/detail drawings, performance curves, package control logic, manuals, FAT/SAT, certificates, vendor calculations.
- EPC Scope: plant integration, civil/structure, foundation, buildings, layout, piping/cable/infrastructure, studies, system diagrams, philosophies, HAZOP/SIL, interface and design criteria documents.

Return only structured output. Keep generation_reason concise and explain why the cited source rows support the generated deliverable.
"""


def expert_candidate_payload(df: pd.DataFrame) -> list[dict[str, object]]:
    payload = []
    for _, row in df.iterrows():
        payload.append(
            {
                "source_standard_no": int(row["No"]),
                "discipline": normalize_cell(row["Discipline"]),
                "document_type": normalize_cell(row["Document Type"]),
                "system": normalize_cell(row["System"]),
                "sub_system": normalize_cell(row["Sub-System"]),
                "equipment": normalize_cell(row["Sub-Sub System (Equipment)"]),
                "standardized_document_title": normalize_cell(row["Standardized Document Title"]),
                "scope_type": normalize_cell(row["Scope Type"]),
                "source_projects": normalize_cell(row["Source Projects"]),
                "source_titles": normalize_cell(row["Source Titles"])[:1000],
            }
        )
    return payload


def run_expert_generation_batch(client: AzureOpenAI, batch_df: pd.DataFrame) -> ExpertGeneratedItemList:
    discipline = normalize_cell(batch_df["Discipline"].iloc[0])
    scope_type = normalize_cell(batch_df["Scope Type"].iloc[0])
    user_message = (
        "Generate a Standard MDL draft supplement from these source-grounded rows.\n"
        f"GROUP_CONTEXT: Discipline={discipline}, Scope Type={scope_type}\n"
        "Return only rows that are Source-Inferred or Expert-Inferred. Do not repeat unchanged Source Title rows.\n\n"
        f"SOURCE_ROWS:\n{json.dumps(expert_candidate_payload(batch_df), ensure_ascii=False, indent=2)}"
    )
    try:
        response = client.chat.completions.parse(
            model=AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": expert_generation_prompt()},
                {"role": "user", "content": user_message},
            ],
            response_format=ExpertGeneratedItemList,
            max_completion_tokens=8000,
        )
    except AttributeError:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": expert_generation_prompt()},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=8000,
        )
    return parse_structured_response(response, ExpertGeneratedItemList)


def iter_expert_generation_batches(standard_df: pd.DataFrame, batch_size: int) -> Iterable[pd.DataFrame]:
    eligible_df = standard_df.copy()
    eligible_df = eligible_df[eligible_df.apply(is_expert_generation_eligible, axis=1)].reset_index(drop=True)
    grouped = eligible_df.groupby(["Discipline", "Scope Type"], sort=True)
    for _, group_df in grouped:
        ordered = group_df.sort_values(
            ["System", "Sub-System", "Sub-Sub System (Equipment)", "Document Type", "Standardized Document Title", "No"],
            kind="stable",
        ).reset_index(drop=True)
        for start in range(0, len(ordered), batch_size):
            yield ordered.iloc[start:start + batch_size].reset_index(drop=True)


def is_expert_generation_eligible(row: pd.Series) -> bool:
    equipment = normalize_cell(row.get("Sub-Sub System (Equipment)"))
    title = normalize_key(row.get("Standardized Document Title"))
    document_type = normalize_key(row.get("Document Type"))
    if not equipment or equipment in GENERIC_TITLE_EQUIPMENT:
        return False
    if any(term in title for term in ["index", "transmittal", "document control", "vendor print", "master document"]):
        return False
    if document_type in {"document", "index", "register"}:
        return False
    return True


def consolidate_expert_augmented_output(
    expert_df: pd.DataFrame,
    audit_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if expert_df.empty:
        return expert_df, audit_df
    expert_df = expert_df.copy()
    priority = {
        "Source Title": 0,
        "Source-Inferred": 1,
        "Expert-Inferred": 2,
    }
    rows: list[dict[str, object]] = []
    for _, group in expert_df.groupby(["Standardized Document Title", "Scope Type"], sort=True, dropna=False):
        group = group.sort_values(
            by=["Evidence Type", "No"],
            key=lambda col: col.map(priority).fillna(99) if col.name == "Evidence Type" else col,
            kind="stable",
        )
        representative = group.iloc[0]
        row = {column: representative.get(column, "") for column in EXPERT_COLUMNS}
        row["Source Projects"] = join_unique_tokens(group["Source Projects"])
        row["Source Document Nos"] = join_unique_tokens(group["Source Document Nos"])
        row["Source Titles"] = join_unique_tokens(group["Source Titles"])
        row["Evidence Type"] = join_unique_tokens(group["Evidence Type"])
        row["Validation Status"] = combine_validation_status(group["Validation Status"])
        row["Review Comment"] = join_unique_tokens(group["Review Comment"])
        row["Source Standard Nos"] = join_unique_tokens(group["Source Standard Nos"])
        row["Review Status"] = choose_review_status(group["Review Status"])
        row["Augmentation Reason"] = join_unique_tokens(group["Augmentation Reason"])
        row["No"] = len(rows) + 1
        rows.append(row)
    consolidated = pd.DataFrame(rows, columns=EXPERT_COLUMNS)
    consolidated = sort_expert_output(consolidated)
    return consolidated, audit_df


def choose_review_status(values: Iterable[object]) -> str:
    statuses = [normalize_cell(value) for value in values if normalize_cell(value)]
    if "Approved Source-Grounded" in statuses:
        return "Approved Source-Grounded"
    if "Needs Doosan Review" in statuses:
        return "Needs Doosan Review"
    return statuses[0] if statuses else "Needs Doosan Review"


def sort_expert_output(expert_df: pd.DataFrame) -> pd.DataFrame:
    if expert_df.empty:
        return expert_df
    sorted_df = expert_df.copy()
    sorted_df["Source Projects"] = sorted_df["Source Projects"].map(sort_joined_projects)
    sorted_df["_discipline_order"] = sorted_df["Discipline"].map(order_index(DISCIPLINE_ORDER))
    sorted_df["_scope_order"] = sorted_df["Scope Type"].map(order_index(SCOPE_ORDER))
    sorted_df["_review_order"] = sorted_df["Review Status"].map(
        order_index(["Approved Source-Grounded", "Needs Doosan Review", "Potential Duplicate", "Covered by Broader Document", "Reject Candidate"])
    )
    sorted_df = sorted_df.sort_values(
        [
            "_review_order",
            "_discipline_order",
            "_scope_order",
            "System",
            "Sub-System",
            "Sub-Sub System (Equipment)",
            "Document Type",
            "Standardized Document Title",
        ],
        kind="stable",
    ).drop(columns=["_discipline_order", "_scope_order", "_review_order"])
    sorted_df["No"] = range(1, len(sorted_df) + 1)
    return sorted_df.reset_index(drop=True)


def build_expert_augmentation_validation(expert_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    if expert_df.empty:
        return pd.DataFrame(rows, columns=VALIDATION_COLUMNS)
    duplicate_groups = expert_df.groupby(["Standardized Document Title", "Scope Type"], dropna=False)
    for _, group in duplicate_groups:
        if len(group) > 1:
            for _, row in group.iterrows():
                rows.append(
                    validation_row(
                        "Duplicate Expert Candidate",
                        "review",
                        row,
                        "Expert augmented output contains duplicate title/scope rows.",
                        "Review duplicate consolidation before Doosan review.",
                    )
                )
    for _, row in expert_df.iterrows():
        title = normalize_cell(row.get("Standardized Document Title"))
        is_added_candidate = normalize_cell(row.get("Review Status")) != "Approved Source-Grounded"
        if is_added_candidate and (not title or normalize_key(title) in {"document", "drawing", "calculation", "report", "foundation drawing"}):
            rows.append(
                validation_row(
                    "Generic Expert Title",
                    "error",
                    row,
                    "Expert augmented title is too generic.",
                    "Revise with equipment and document type before review.",
                )
            )
        evidence_type = normalize_cell(row.get("Evidence Type"))
        if "Expert-Inferred" in evidence_type:
            if normalize_cell(row.get("Review Status")) != "Needs Doosan Review":
                rows.append(
                    validation_row(
                        "Expert Review Status Error",
                        "error",
                        row,
                        "Expert-Inferred row is not marked as Needs Doosan Review.",
                        "Set Review Status to Needs Doosan Review before sharing the draft.",
                    )
                )
            if not normalize_cell(row.get("Source Standard Nos")):
                rows.append(
                    validation_row(
                        "Expert Source Reference Missing",
                        "error",
                        row,
                        "Expert-Inferred row does not cite source Standard MDL row numbers.",
                        "Reject the row or regenerate it with source_standard_nos from the LLM prompt batch.",
                    )
                )
            if not normalize_cell(row.get("Source Titles")):
                rows.append(
                    validation_row(
                        "Expert Source Title Missing",
                        "review",
                        row,
                        "Expert-Inferred row does not retain source title evidence.",
                        "Keep source title evidence so reviewers can trace the package/system/equipment basis.",
                    )
                )
    return pd.DataFrame(rows, columns=VALIDATION_COLUMNS)


def validate_standard_rows(standard_df: pd.DataFrame) -> list[dict[str, str]]:
    rows = []
    for _, row in standard_df.iterrows():
        status = normalize_cell(row.get("Validation Status"))
        if not status or status == "OK":
            continue
        for item in [part.strip() for part in status.split(";") if part.strip()]:
            rows.append(
                validation_row(
                    item,
                    "review",
                    row,
                    reason=normalize_cell(row.get("Review Comment")) or item,
                    action="Review source titles and adjust standardized title or scope if needed.",
                )
            )
    return rows


def validate_non_document_standard_titles(standard_df: pd.DataFrame) -> list[dict[str, str]]:
    rows = []
    for _, row in standard_df.iterrows():
        title = normalize_cell(row.get("Standardized Document Title"))
        source_titles = normalize_cell(row.get("Source Titles"))
        if is_non_document_title(title) or any(pattern.search(source_titles) for pattern in NON_DOCUMENT_TITLE_PATTERNS):
            rows.append(
                validation_row(
                    "Non-Document Title",
                    "error",
                    row,
                    reason="Standard title or source title appears to be a date, PO basis, internal note, or other metadata rather than a deliverable.",
                    action="Remove from Standard MDL or correct source classification before ITB comparison.",
                )
            )
    return rows


def validate_duplicate_standard_titles(standard_df: pd.DataFrame) -> list[dict[str, str]]:
    rows = []
    duplicate_groups = standard_df.groupby(["Standardized Document Title", "Scope Type"], dropna=False)
    for _, group in duplicate_groups:
        if len(group) <= 1:
            continue
        for _, row in group.iterrows():
            rows.append(
                validation_row(
                    "Duplicate Standard Title",
                    "review",
                    row,
                    reason=f"{len(group)} rows share the same Standardized Document Title and Scope Type.",
                    action="Merge if they are the same deliverable; otherwise revise title with equipment/area/purpose context.",
                )
            )
    return rows


def validate_vendor_epc_ambiguity(standard_df: pd.DataFrame) -> list[dict[str, str]]:
    rows = []
    grouped = standard_df.groupby("Standardized Document Title", dropna=False)
    for _, group in grouped:
        scopes = {normalize_cell(value) for value in group["Scope Type"]}
        if not {"Vendor", "EPC"} <= scopes:
            continue
        for _, row in group.iterrows():
            rows.append(
                validation_row(
                    "Vendor EPC Ambiguity",
                    "review",
                    row,
                    reason="Same standardized title exists in both Vendor and EPC scope.",
                    action="Clarify scope in the title or correct Scope Type to prevent mixed responsibility.",
                )
            )
    return rows


def validate_foundation_gaps(standard_df: pd.DataFrame) -> list[dict[str, str]]:
    rows = []
    equipment_names = {
        normalize_cell(row["Sub-Sub System (Equipment)"])
        for _, row in standard_df.iterrows()
        if is_major_foundation_equipment(row["Sub-Sub System (Equipment)"])
    }
    title_text = "\n".join(standard_df["Standardized Document Title"].astype(str).tolist())
    title_key = normalize_key(title_text)
    required_docs = [
        "Foundation Drawing",
        "Foundation Reinforcement Drawing",
        "Foundation Design Calculation",
    ]
    for equipment in sorted(equipment_names):
        equipment_key = normalize_key(equipment)
        for document_type in required_docs:
            expected = f"{equipment} {document_type}"
            if equipment_key and normalize_key(expected) not in title_key:
                rows.append(
                    {
                        "validation_type": "Missing Foundation Candidate",
                        "severity": "review",
                        "discipline": "Civil/Structural",
                        "scope_type": "EPC",
                        "system": "Civil / Site Infrastructure System",
                        "sub_system": f"{equipment} Foundation",
                        "equipment": f"{equipment} Foundation",
                        "document_type": document_type,
                        "standardized_document_title": expected,
                        "reason": f"Major physical equipment '{equipment}' exists, but '{document_type}' was not found in the integrated MDL.",
                        "recommended_action": "Do not auto-add yet; Doosan review should confirm whether this foundation deliverable is required.",
                    }
                )
    return rows


def is_major_foundation_equipment(equipment: object) -> bool:
    key = normalize_key(equipment)
    if not key or key in {"plant general", "general area"}:
        return False
    exclude = [
        "valve",
        "transmitter",
        "gauge",
        "flow element",
        "junction box",
        "cable",
        "tray",
        "conduit",
        "instrument rack",
        "panel",
        "local box",
        "thermowell",
    ]
    if any(term in key for term in exclude):
        return False
    include = [
        "gas turbine",
        "steam turbine",
        "generator",
        "heat recovery steam generator",
        "hrsg",
        "air cooled condenser",
        "acc",
        "pump",
        "tank",
        "compressor",
        "transformer",
        "edg",
        "diesel generator",
        "cooling tower",
        "module",
        "boiler",
        "heat exchanger",
        "fin fan cooler",
        "crane",
        "switchgear",
        "mcc",
    ]
    return any(term in key for term in include)


def validate_building_structure_gaps(standard_df: pd.DataFrame) -> list[dict[str, str]]:
    rows = []
    buildings = {
        normalize_cell(value).replace(" Structure", "")
        for value in standard_df["Sub-Sub System (Equipment)"].astype(str)
        if "building" in normalize_key(value)
    }
    title_key = normalize_key("\n".join(standard_df["Standardized Document Title"].astype(str).tolist()))
    building_parts = ["Building Foundation", "Structural Frame", "Roof Structure", "Floor Structure"]
    doc_types = ["Structural Calculation", "General Arrangement Drawing", "Reinforcement Drawing"]
    for building in sorted(buildings):
        for part in building_parts:
            for doc_type in doc_types:
                expected = f"{building} {part} {doc_type}"
                if normalize_key(expected) not in title_key:
                    rows.append(
                        {
                            "validation_type": "Missing Building Structure Candidate",
                            "severity": "review",
                            "discipline": "Civil/Structural",
                            "scope_type": "EPC",
                            "system": "Building / Structure System",
                            "sub_system": building,
                            "equipment": f"{building} {part}",
                            "document_type": doc_type,
                            "standardized_document_title": expected,
                            "reason": "Building structure breakdown candidate was not found as a standard MDL item.",
                            "recommended_action": "Review whether this building breakdown should be added to the Standard MDL.",
                        }
                    )
    return rows


def validate_study_gaps(standard_df: pd.DataFrame) -> list[dict[str, str]]:
    rows = []
    title_key = normalize_key("\n".join(standard_df["Standardized Document Title"].astype(str).tolist()))
    expected_studies = [
        ("Electrical", "Electrical Network Model Load Flow Study"),
        ("Electrical", "Electrical Network Model Short Circuit Study"),
        ("Electrical", "Electrical Network Model Motor Starting Study"),
        ("Process", "Plant Safety Model HAZOP Study"),
        ("Process", "Plant Safety Model SIL Study"),
    ]
    for discipline, expected in expected_studies:
        if normalize_key(expected) not in title_key:
            rows.append(
                {
                    "validation_type": "Missing Study Candidate",
                    "severity": "review",
                    "discipline": discipline,
                    "scope_type": "EPC",
                    "system": "Plant Study / Analysis System",
                    "sub_system": "Study / Analysis",
                    "equipment": expected.rsplit(" ", 1)[0],
                    "document_type": expected.split()[-1],
                    "standardized_document_title": expected,
                    "reason": "Common study deliverable was not found as a standard MDL item.",
                    "recommended_action": "Review source MDLs and decide whether the study should be included as standard.",
                }
            )
    return rows


def validation_row(validation_type: str, severity: str, row: pd.Series, reason: str, action: str) -> dict[str, str]:
    return {
        "validation_type": validation_type,
        "severity": severity,
        "discipline": normalize_cell(row.get("Discipline")),
        "scope_type": normalize_cell(row.get("Scope Type")),
        "system": normalize_cell(row.get("System")),
        "sub_system": normalize_cell(row.get("Sub-System")),
        "equipment": normalize_cell(row.get("Sub-Sub System (Equipment)")),
        "document_type": normalize_cell(row.get("Document Type")),
        "standardized_document_title": normalize_cell(row.get("Standardized Document Title")),
        "reason": reason,
        "recommended_action": action,
    }


def build_summary(source_df: pd.DataFrame, standard_df: pd.DataFrame, audit_df: pd.DataFrame, validation_df: pd.DataFrame, rejection_df: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        ("source_rows", len(source_df)),
        ("standard_mdl_rows", len(standard_df)),
        ("source_mapping_rows", len(audit_df)),
        ("validation_rows", len(validation_df)),
        ("rejection_rows", len(rejection_df)),
    ]
    for project, count in source_df["Source Project"].value_counts().sort_index().items():
        metrics.append((f"source_rows:{project}", count))
    for discipline, count in standard_df["Discipline"].value_counts().sort_index().items():
        metrics.append((f"standard_rows_by_discipline:{discipline}", count))
    for scope_type, count in standard_df["Scope Type"].value_counts().sort_index().items():
        metrics.append((f"standard_rows_by_scope:{scope_type}", count))
    for status, count in standard_df["Validation Status"].value_counts().sort_index().items():
        metrics.append((f"validation_status:{status}", count))
    return pd.DataFrame(metrics, columns=SUMMARY_COLUMNS)


def write_outputs(output_dir: Path, standard_df: pd.DataFrame, audit_df: pd.DataFrame, validation_df: pd.DataFrame, rejection_df: pd.DataFrame, summary_df: pd.DataFrame) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    standard_df, audit_df = sort_standard_and_audit(standard_df, audit_df, "standard_no", "standardized_document_title")
    standard_csv = output_dir / "integrated_standard_mdl.csv"
    audit_csv = output_dir / "source_mapping_audit.csv"
    validation_csv = output_dir / "validation_report.csv"
    rejections_csv = output_dir / "rejections.csv"
    excel_path = output_dir / "integrated_standard_mdl.xlsx"

    standard_df.to_csv(standard_csv, index=False, encoding="utf-8-sig")
    audit_df.to_csv(audit_csv, index=False, encoding="utf-8-sig")
    validation_df.to_csv(validation_csv, index=False, encoding="utf-8-sig")
    rejection_df.to_csv(rejections_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        standard_df.to_excel(writer, sheet_name="Integrated Standard MDL", index=False)
        audit_df.to_excel(writer, sheet_name="Source Mapping Audit", index=False)
        validation_df.to_excel(writer, sheet_name="Validation Report", index=False)
        rejection_df.to_excel(writer, sheet_name="Rejections", index=False)
        summary_df.to_excel(writer, sheet_name="Run Summary", index=False)


def write_llm_outputs(
    output_dir: Path,
    standard_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    rejection_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    pilot: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    standard_df, audit_df = sort_standard_and_audit(standard_df, audit_df, "llm_standard_no", "llm_standardized_document_title")
    prefix = "pilot_llm" if pilot else "llm"
    standard_csv = output_dir / f"{prefix}_integrated_standard_mdl.csv"
    audit_csv = output_dir / f"{prefix}_merge_audit.csv"
    validation_csv = output_dir / f"{prefix}_validation_report.csv"
    rejections_csv = output_dir / f"{prefix}_merge_rejections.csv"
    excel_path = output_dir / f"{prefix}_integrated_standard_mdl.xlsx"

    standard_df.to_csv(standard_csv, index=False, encoding="utf-8-sig")
    audit_df.to_csv(audit_csv, index=False, encoding="utf-8-sig")
    validation_df.to_csv(validation_csv, index=False, encoding="utf-8-sig")
    rejection_df.to_csv(rejections_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        standard_df.to_excel(writer, sheet_name="LLM Integrated Standard MDL", index=False)
        audit_df.to_excel(writer, sheet_name="LLM Merge Audit", index=False)
        validation_df.to_excel(writer, sheet_name="LLM Validation Report", index=False)
        rejection_df.to_excel(writer, sheet_name="LLM Rejections", index=False)
        summary_df.to_excel(writer, sheet_name="Run Summary", index=False)


def write_expert_augmented_outputs(
    output_dir: Path,
    expert_df: pd.DataFrame,
    expert_audit_df: pd.DataFrame,
    expert_validation_df: pd.DataFrame,
    summary_df: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    standard_csv = output_dir / "expert_prompt_standard_mdl.csv"
    audit_csv = output_dir / "expert_prompt_audit.csv"
    validation_csv = output_dir / "expert_prompt_validation.csv"
    excel_path = output_dir / "expert_prompt_standard_mdl.xlsx"

    expert_df.to_csv(standard_csv, index=False, encoding="utf-8-sig")
    expert_audit_df.to_csv(audit_csv, index=False, encoding="utf-8-sig")
    expert_validation_df.to_csv(validation_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        expert_df.to_excel(writer, sheet_name="Expert Prompt MDL", index=False)
        expert_audit_df.to_excel(writer, sheet_name="Expert Prompt Audit", index=False)
        expert_validation_df.to_excel(writer, sheet_name="Expert Prompt Validation", index=False)
        summary_df.to_excel(writer, sheet_name="Run Summary", index=False)


def build_llm_summary(rule_standard_df: pd.DataFrame, llm_standard_df: pd.DataFrame, llm_audit_df: pd.DataFrame, llm_validation_df: pd.DataFrame, llm_rejection_df: pd.DataFrame, pilot: bool) -> pd.DataFrame:
    metrics = [
        ("mode", "pilot" if pilot else "full"),
        ("rule_standard_rows_input", len(rule_standard_df)),
        ("llm_standard_rows", len(llm_standard_df)),
        ("llm_merge_audit_rows", len(llm_audit_df)),
        ("llm_validation_rows", len(llm_validation_df)),
        ("llm_rejection_rows", len(llm_rejection_df)),
    ]
    for discipline, count in llm_standard_df["Discipline"].value_counts().sort_index().items():
        metrics.append((f"llm_rows_by_discipline:{discipline}", count))
    for scope_type, count in llm_standard_df["Scope Type"].value_counts().sort_index().items():
        metrics.append((f"llm_rows_by_scope:{scope_type}", count))
    for status, count in llm_standard_df["Validation Status"].value_counts().sort_index().items():
        metrics.append((f"llm_validation_status:{status}", count))
    return pd.DataFrame(metrics, columns=SUMMARY_COLUMNS)


def build_expert_summary(base_df: pd.DataFrame, expert_df: pd.DataFrame, expert_audit_df: pd.DataFrame, expert_validation_df: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        ("base_standard_rows", len(base_df)),
        ("expert_augmented_rows", len(expert_df)),
        ("expert_added_rows", int((expert_df["Evidence Type"].astype(str).str.contains("Expert-Inferred", na=False) & ~expert_df["Evidence Type"].astype(str).eq("Source Title")).sum()) if not expert_df.empty else 0),
        ("expert_audit_rows", len(expert_audit_df)),
        ("expert_validation_rows", len(expert_validation_df)),
        ("copilot_used_for_generation", "false"),
    ]
    if not expert_df.empty:
        for evidence_type, count in expert_df["Evidence Type"].value_counts().sort_index().items():
            metrics.append((f"expert_rows_by_evidence:{evidence_type}", count))
        for review_status, count in expert_df["Review Status"].value_counts().sort_index().items():
            metrics.append((f"expert_rows_by_review_status:{review_status}", count))
        for scope_type, count in expert_df["Scope Type"].value_counts().sort_index().items():
            metrics.append((f"expert_rows_by_scope:{scope_type}", count))
    return pd.DataFrame(metrics, columns=SUMMARY_COLUMNS)


def load_standard_mdl_xlsx(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Expert base Standard MDL not found: {path}")
    excel = pd.ExcelFile(path)
    preferred_sheets = ["LLM Integrated Standard MDL", "Integrated Standard MDL", excel.sheet_names[0]]
    for sheet in preferred_sheets:
        if sheet in excel.sheet_names:
            df = pd.read_excel(path, sheet_name=sheet).fillna("")
            break
    else:
        df = pd.read_excel(path, sheet_name=0).fillna("")
    for column in STANDARD_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[STANDARD_COLUMNS].copy()
    if not df.empty:
        df["No"] = range(1, len(df) + 1)
    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build integrated Standard MDL before ITB comparison.")
    parser.add_argument("--input-dir", type=Path, default=OUTPUT_DIR, help="Directory containing seven *_MDL_classified.csv files.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR / "standard_mdl", help="Directory for Standard MDL outputs.")
    parser.add_argument("--llm-merge", action="store_true", help="Run LLM semantic merge after rule-based Standard MDL generation.")
    parser.add_argument("--pilot", action="store_true", help="With --llm-merge, only run the pilot discipline/scope/document-type groups.")
    parser.add_argument("--llm-batch-size", type=int, default=60, help="Number of rule-based standard rows per LLM merge batch.")
    parser.add_argument("--expert-augment", action="store_true", help="Create an LLM expert-inferred review candidate layer after Standard MDL generation. Copilot files are not used.")
    parser.add_argument("--expert-batch-size", type=int, default=50, help="Number of source-grounded standard rows per LLM expert generation batch.")
    parser.add_argument("--expert-base-xlsx", type=Path, help="Existing Standard MDL workbook to use as expert augmentation baseline. Copilot workbooks must not be passed here.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_df, rejection_df = load_classified_mdls(args.input_dir)
    enriched_df = enrich_source_rows(source_df)
    standard_df, audit_df = build_integrated_standard_mdl(enriched_df)
    validation_df = build_validation_report(standard_df)
    summary_df = build_summary(source_df, standard_df, audit_df, validation_df, rejection_df)
    write_outputs(args.output_dir, standard_df, audit_df, validation_df, rejection_df, summary_df)

    print("[STANDARD-MDL] source rows:", len(source_df), flush=True)
    print("[STANDARD-MDL] standard rows:", len(standard_df), flush=True)
    print("[STANDARD-MDL] source mapping rows:", len(audit_df), flush=True)
    print("[STANDARD-MDL] validation rows:", len(validation_df), flush=True)
    print("[STANDARD-MDL] rejections:", len(rejection_df), flush=True)
    print("[STANDARD-MDL] wrote:", args.output_dir / "integrated_standard_mdl.xlsx", flush=True)
    expert_base_df = standard_df
    expert_base_validation_df = validation_df
    if args.llm_merge:
        llm_standard_df, llm_audit_df, llm_rejection_df = build_llm_refined_mdl(
            standard_df,
            audit_df,
            pilot=args.pilot,
            batch_size=args.llm_batch_size,
        )
        llm_validation_df = build_validation_report(llm_standard_df)
        llm_summary_df = build_llm_summary(
            standard_df,
            llm_standard_df,
            llm_audit_df,
            llm_validation_df,
            llm_rejection_df,
            pilot=args.pilot,
        )
        write_llm_outputs(
            args.output_dir,
            llm_standard_df,
            llm_audit_df,
            llm_validation_df,
            llm_rejection_df,
            llm_summary_df,
            pilot=args.pilot,
        )
        prefix = "pilot_llm" if args.pilot else "llm"
        print(f"[STANDARD-MDL][LLM] mode: {'pilot' if args.pilot else 'full'}", flush=True)
        print("[STANDARD-MDL][LLM] standard rows:", len(llm_standard_df), flush=True)
        print("[STANDARD-MDL][LLM] audit rows:", len(llm_audit_df), flush=True)
        print("[STANDARD-MDL][LLM] validation rows:", len(llm_validation_df), flush=True)
        print("[STANDARD-MDL][LLM] rejections:", len(llm_rejection_df), flush=True)
        print("[STANDARD-MDL][LLM] wrote:", args.output_dir / f"{prefix}_integrated_standard_mdl.xlsx", flush=True)
        expert_base_df = llm_standard_df
        expert_base_validation_df = llm_validation_df
    if args.expert_augment:
        if args.expert_base_xlsx:
            expert_base_df = load_standard_mdl_xlsx(args.expert_base_xlsx)
            expert_base_validation_df = build_validation_report(expert_base_df)
        expert_df, expert_audit_df, expert_validation_df = build_expert_augmented_mdl(
            expert_base_df,
            expert_base_validation_df,
            batch_size=args.expert_batch_size,
        )
        expert_summary_df = build_expert_summary(expert_base_df, expert_df, expert_audit_df, expert_validation_df)
        write_expert_augmented_outputs(
            args.output_dir,
            expert_df,
            expert_audit_df,
            expert_validation_df,
            expert_summary_df,
        )
        print("[STANDARD-MDL][EXPERT] base rows:", len(expert_base_df), flush=True)
        print("[STANDARD-MDL][EXPERT] augmented rows:", len(expert_df), flush=True)
        print("[STANDARD-MDL][EXPERT] audit rows:", len(expert_audit_df), flush=True)
        print("[STANDARD-MDL][EXPERT] validation rows:", len(expert_validation_df), flush=True)
        print("[STANDARD-MDL][EXPERT] wrote:", args.output_dir / "expert_prompt_standard_mdl.xlsx", flush=True)
    return 0 if not standard_df.empty else 1


if __name__ == "__main__":
    sys.exit(main())
