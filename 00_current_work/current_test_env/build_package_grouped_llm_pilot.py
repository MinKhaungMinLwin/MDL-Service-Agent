"""Build a package-grouped LLM pilot Standard MDL.

Pilot scope:
- Input projects: Fadhili and R&N only.
- Vendor package groups: ACC, HRSG, DCS.
- EPC group: all EPC source-grounded candidates from the two projects.

The script keeps build_standard_mdl.py unchanged. It uses the existing
source-grounded rule pass only to reduce raw MDL rows into traceable candidates,
then asks the LLM to merge, standardize, and add review-only supplement rows per
package/scope group.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

import pandas as pd
from pydantic import BaseModel, Field

import build_standard_mdl as base
from mdl_runtime.config import AZURE_OPENAI_CHAT_DEPLOYMENT, OUTPUT_DIR


PROMPT_PATH = Path(__file__).resolve().parent / "ccpp_document_classification_prompt_260423.md"
FORCED_TAXONOMY_PATH = Path(__file__).resolve().parent / "data" / "lv1lv2강제프롬프트.docx"

PILOT_PROJECTS = {
    "Fadhili": "Fadhili_MDL_classified.csv",
    "R&N": "R&N_MDL_classified.csv",
}

PACKAGE_MARKERS = {
    "ACC": ["acc", "air cooled condenser", "air cool condenser"],
    "HRSG": ["hrsg", "heat recovery steam generator"],
    "DCS": ["dcs", "distributed control system", "plant control system"],
}

PACKAGE_SECTION_TITLE = {
    "ACC": "ACC Vendor Document List",
    "HRSG": "HRSG Vendor Document List",
    "DCS": "DCS Vendor Document List",
    "EPC": "EPC Document List",
}

LEVEL1_ALIAS_GROUPS = [
    ("Auxiliary Steam", ["Aux Steam", "Auxiliary Steam"]),
    ("Steam System(High Pressure)", ["Steam System(High Pressure)", "High Pressure(HP)", "High Pressure", "HP"]),
    ("Steam System(Cold Reheat)", ["Steam System(Cold Reheat)", "Cold Reheat(CRH)", "Cold Reheat", "CRH"]),
    ("Steam System(Hot Reheat)", ["Steam System(Hot Reheat)", "Hot Reheat(HRH)", "Hot Reheat", "HRH"]),
    ("Steam System(Low Pressure)", ["Steam System(Low Pressure)", "Low Pressure(LP)", "Low Pressure", "LP"]),
    ("Condensate System", ["Condensate System", "Water System(Condensate)"]),
    ("Water System(Feedwater)", ["Water System(Feedwater)", "Feed Water System", "Feedwater System"]),
    ("Instrument & Control System", ["Instrument & Control System", "I&C", "Instrumentation & Control"]),
    ("Intermediate Pressure", ["Intermediate Pressure", "Intermediate Pressure(IP)", "IP"]),
]

LEVEL2_ALIAS_GROUPS = [
    ("HRSG", ["HRSG", "Heat Recovery Steam Generator"]),
    ("DCS", ["DCS", "Distributed Control System", "Plant Control System"]),
    ("Gas Turbine", ["Gas Turbine", "Gas Turbine(GT)", "GT"]),
    ("Gas Turbine Generator(GTG)", ["Gas Turbine Generator(GTG)", "Gas Turbine Generator", "GTG"]),
    ("Steam Turbine", ["Steam Turbine", "Steam Turbine(ST)", "ST"]),
    ("Steam Turbine Generator(GTG)", ["Steam Turbine Generator(GTG)", "Steam Turbine Generator", "STG"]),
    ("MV Switchgear", ["MV SWGR", "MV Switchgear", "MV_SWGR"]),
    ("LV Switchgear", ["LV SWGR", "LV Switchgear", "LV_SWGR"]),
    ("EDG", ["EDG", "BSEDG", "BSDG", "Emergency Diesel Generator", "Blackstart Diesel Generator"]),
    ("Auxiliary", ["Aux", "Auxiliary"]),
    ("Air Cooled Condenser", ["ACC", "Air Cooled Condenser", "Air Cool Condenser"]),
    ("CCB", ["CCB", "CENTRAL CONTROL BUILDING", "Central Control Building", "Control Center"]),
    ("LEB", ["LEB", "Electrical Building", "Local Electrical Building"]),
    ("WTB", ["WTB", "WT Building", "Water Treatment Building"]),
    ("Pipe Rack", ["Pipe Rack", "PR", "Pipe Rack(PR)"]),
    ("Cable Rack", ["Cable Rack", "CR", "Cable Rack(CR)"]),
]

TITLE_ABBREVIATIONS = [
    (r"\bHeat Recovery Steam Generator\b", "HRSG"),
    (r"\bAir[- ]Cooled Condenser\b", "ACC"),
    (r"\bAir Cool Condenser\b", "ACC"),
    (r"\bDistributed Control System\b", "DCS"),
    (r"\bPlant Control System\b", "DCS"),
    (r"\bGas Turbine Generator\b", "GTG"),
    (r"\bSteam Turbine Generator\b", "STG"),
    (r"\bGenerator Circuit Breaker\b", "GCB"),
    (r"\bGenerator Step[- ]Up Transformer\b", "GSUT"),
    (r"\bBalance of Plant\b", "BOP"),
    (r"\bMotor Operated Valve\b", "MOV"),
    (r"\bPiping\s*(?:&|and)\s*Instrumentation\s*(?:Drawing|Diagram)\b", "P&ID"),
    (r"\bInstrumentation\s*(?:&|and)\s*Control\b", "I&C"),
    (r"\bMedium Voltage\b", "MV"),
    (r"\bLow Voltage\b", "LV"),
    (r"\bUninterrupt(?:ible|ed) Power Supply\b", "UPS"),
]

FLAT_COLUMNS = [
    "No",
    "Section",
    "Package/Scope Group",
    "Discipline",
    "Document Type",
    "System (L1)",
    "Sub-System / Area (L2)",
    "Equipment (L3)",
    "Standardized Document Title",
    "Scope",
    "Evidence Type",
    "Review Status",
    "Source Standard Nos",
    "Source Projects",
    "Source Document Nos",
    "Source Titles",
    "Generation / Merge Reason",
]

AUDIT_COLUMNS = [
    "output_no",
    "section",
    "standardized_document_title",
    "source_standard_no",
    "source_projects",
    "source_document_nos",
    "source_titles",
    "llm_reason",
]

REJECTION_COLUMNS = [
    "group",
    "batch",
    "source_standard_no",
    "standardized_document_title",
    "reason",
    "raw_payload",
]


class GroupedLLMItem(BaseModel):
    discipline: str
    document_type: str
    system_l1: str
    sub_system_l2: str
    equipment_l3: str
    standardized_document_title: str
    scope: str = Field(description="Vendor or EPC")
    evidence_type: str = Field(description="Source-Grounded, Source-Inferred, or Expert-Inferred")
    source_standard_nos: list[int]
    review_status: str = Field(description="Approved Source-Grounded or Needs Doosan Review")
    generation_merge_reason: str


class GroupedLLMItemList(BaseModel):
    items: list[GroupedLLMItem]


def extract_docx_paragraphs(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
        text = base.normalize_cell(text)
        if text:
            paragraphs.append(text)
    return paragraphs


def split_docx_terms(text: str) -> list[str]:
    if "동일의미 표기" in text:
        text = text.split("동일의미 표기", 1)[1]
    text = re.sub(r"여기\s*포함되지\s*않으면\s*General로\s*구분.*$", "", text).strip()
    terms: list[str] = []
    for raw in text.split(","):
        term = base.normalize_cell(raw)
        if not term:
            continue
        if term in {"1. Equipment : Equipment 에 따른 구분 Level2 강제(이 안에서만 구분)", "2. Building: Building에 따른 구분 Level2 강제(이 안에서만 구분)"}:
            continue
        terms.append(term)
    return list(dict.fromkeys(terms))


@lru_cache(maxsize=1)
def forced_taxonomy() -> dict[str, object]:
    paragraphs = extract_docx_paragraphs(FORCED_TAXONOMY_PATH)
    equipment_terms: list[str] = []
    building_terms: list[str] = []
    system_terms: list[str] = []
    for paragraph in paragraphs:
        if paragraph.startswith("1. Equipment : 발전"):
            equipment_terms = split_docx_terms(paragraph)
        elif paragraph.startswith("2. Building:"):
            building_terms = split_docx_terms(paragraph)
        elif paragraph.startswith("3. System:"):
            system_terms = split_docx_terms(paragraph)

    system_aliases = build_alias_map(system_terms, LEVEL1_ALIAS_GROUPS)
    level2_terms = list(dict.fromkeys([*equipment_terms, *building_terms, "General"]))
    level2_aliases = build_alias_map(level2_terms, LEVEL2_ALIAS_GROUPS)
    return {
        "systems": system_terms,
        "level2": level2_terms,
        "system_aliases": system_aliases,
        "level2_aliases": level2_aliases,
    }


def build_alias_map(allowed_terms: list[str], alias_groups: list[tuple[str, list[str]]]) -> dict[str, str]:
    allowed_by_key = {base.normalize_key(term): term for term in allowed_terms if base.normalize_key(term)}
    alias_map = {term: term for term in allowed_terms}
    for canonical, aliases in alias_groups:
        canonical_value = allowed_by_key.get(base.normalize_key(canonical), canonical)
        for alias in aliases:
            alias_map[alias] = canonical_value
    return alias_map


def taxonomy_text_limit(values: Iterable[object], limit: int = 180) -> str:
    tokens = [base.normalize_cell(value) for value in values if base.normalize_cell(value)]
    if len(tokens) <= limit:
        return ", ".join(tokens)
    return ", ".join(tokens[:limit]) + f", ... (+{len(tokens) - limit} more)"


def match_allowed_value(text: str, alias_map: dict[str, str]) -> str:
    haystack = f" {base.normalize_key(text)} "
    if not haystack.strip():
        return ""
    for alias, canonical in sorted(alias_map.items(), key=lambda item: len(base.normalize_key(item[0])), reverse=True):
        key = base.normalize_key(alias)
        if key and f" {key} " in haystack:
            return canonical
    return ""


def row_context_text(
    source_rows: list[pd.Series],
    item: GroupedLLMItem | None = None,
    extra_values: Iterable[object] = (),
) -> str:
    parts: list[str] = []
    if item is not None:
        parts.extend(
            [
                item.system_l1,
                item.sub_system_l2,
                item.equipment_l3,
                item.standardized_document_title,
                item.document_type,
                item.generation_merge_reason,
            ]
        )
    parts.extend(base.normalize_cell(value) for value in extra_values)
    for row in source_rows:
        for column in [
            "System",
            "Sub-System",
            "Sub-Sub System (Equipment)",
            "Standardized Document Title",
            "Source Titles",
            "Document Type",
        ]:
            parts.append(base.normalize_cell(row.get(column)))
    return " | ".join(part for part in parts if part)


def forced_system_l1(source_rows: list[pd.Series], item: GroupedLLMItem | None = None, extra_values: Iterable[object] = ()) -> str:
    taxonomy = forced_taxonomy()
    text = row_context_text(source_rows, item, extra_values)
    matched = match_allowed_value(text, taxonomy["system_aliases"])  # type: ignore[index]
    if matched:
        return matched
    systems = taxonomy["systems"]  # type: ignore[index]
    if "Plant General System" in systems:
        return "Plant General System"
    return base.normalize_cell(systems[0]) if systems else "General"


def forced_sub_system_l2(source_rows: list[pd.Series], item: GroupedLLMItem | None = None, extra_values: Iterable[object] = ()) -> str:
    taxonomy = forced_taxonomy()
    text = row_context_text(source_rows, item, extra_values)
    matched = match_allowed_value(text, taxonomy["level2_aliases"])  # type: ignore[index]
    return matched or "General"


def remove_project_qualifiers(text: object) -> str:
    title = base.normalize_cell(text)
    if not title:
        return ""
    title = re.sub(r"\s*\(\s*(?:for\s+)?(?:block|unit|project)\s+[^)]*\)", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\[\s*(?:for\s+)?(?:block|unit|project)\s+[^\]]*\]", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\bfor\s+(?:block|unit|project)\s+[0-9A-Za-z,&/ -]+(?=\s+(?:Data|Drawing|Drawings|List|Report|Calculation|Specification|Procedure|Manual|Curve|Diagram|Description|Schedule|Index)\b|$)", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:block|unit|project)\s+[0-9A-Za-z,&/ -]+(?=\s+(?:Data|Drawing|Drawings|List|Report|Calculation|Specification|Procedure|Manual|Curve|Diagram|Description|Schedule|Index)\b)", " ", title, flags=re.IGNORECASE)
    return base.normalize_cell(title)


def apply_title_abbreviations(text: object) -> str:
    title = base.normalize_cell(text)
    for pattern, replacement in TITLE_ABBREVIATIONS:
        title = re.sub(pattern, replacement, title, flags=re.IGNORECASE)
    return base.normalize_cell(title)


def normalize_standardized_title(text: object) -> str:
    title = remove_project_qualifiers(text)
    title = apply_title_abbreviations(title)
    title = re.sub(r"\s*&\s*", " & ", title)
    return base.normalize_cell(title)


def normalize_equipment_l3(value: object, source_rows: list[pd.Series], item: GroupedLLMItem | None = None) -> str:
    equipment = remove_project_qualifiers(value)
    equipment = apply_title_abbreviations(equipment)
    if equipment and base.normalize_key(equipment) not in {"general", "document", "equipment", "package"}:
        return equipment
    if item is not None:
        inferred = remove_project_qualifiers(item.standardized_document_title)
        inferred = re.sub(
            r"\b(?:Data\s*Sheet|Datasheet|Drawing|Drawings|Calculation|Report|List|Procedure|Manual|Specification|Schedule|Diagram|Layout|Plan|Detail|Arrangement)\b.*$",
            "",
            inferred,
            flags=re.IGNORECASE,
        )
        inferred = apply_title_abbreviations(inferred)
        if inferred and base.normalize_key(inferred) not in {"general", "document", "equipment", "package"}:
            return inferred
    fallback = base.choose_context_value(row.get("Sub-Sub System (Equipment)") for row in source_rows)
    fallback = remove_project_qualifiers(fallback)
    fallback = apply_title_abbreviations(fallback)
    return fallback or "General"


def split_composite_deliverable_rows(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    patterns = [
        (re.compile(r"\bData\s*Sheets?\s*&\s*Drawings?\b", re.IGNORECASE), ["Data Sheet", "Drawing"]),
        (re.compile(r"\bData\s*Sheets?\s+and\s+Drawings?\b", re.IGNORECASE), ["Data Sheet", "Drawing"]),
        (re.compile(r"\bDatasheets?\s*&\s*Drawings?\b", re.IGNORECASE), ["Data Sheet", "Drawing"]),
        (re.compile(r"\bDatasheets?\s+and\s+Drawings?\b", re.IGNORECASE), ["Data Sheet", "Drawing"]),
    ]
    for _, row in df.iterrows():
        title = base.normalize_cell(row.get("Standardized Document Title"))
        matched_pattern = None
        replacements: list[str] = []
        for pattern, replacement_values in patterns:
            if pattern.search(title):
                matched_pattern = pattern
                replacements = replacement_values
                break
        if matched_pattern is None:
            rows.append(row.to_dict())
            continue
        for replacement in replacements:
            updated = row.to_dict()
            updated["Document Type"] = replacement
            updated["Standardized Document Title"] = normalize_standardized_title(matched_pattern.sub(replacement, title))
            updated["Generation / Merge Reason"] = base.join_unique(
                [
                    row.get("Generation / Merge Reason"),
                    "Composite deliverable split: Data Sheet & Drawings separated by Standard MDL naming rule.",
                ]
            )
            rows.append(updated)
    return pd.DataFrame(rows, columns=df.columns)


def load_ccpp_expert_context() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    markers = ["## Persona", "## Major Equipment Design Expertise:", "## Auxiliary Equipment Design Expertise:", "## Design Professional Capabilities:", "### 6. Deliverable", "## Abbreviation Dictionary"]
    chunks: list[str] = []
    for index, marker in enumerate(markers):
        start = text.find(marker)
        if start < 0:
            continue
        next_positions = [text.find(next_marker, start + len(marker)) for next_marker in markers[index + 1 :]]
        next_positions = [position for position in next_positions if position >= 0]
        end = min(next_positions) if next_positions else len(text)
        chunks.append(text[start:end].strip())
    return "\n\n".join(chunks)


def load_source(input_dir: Path, project_files: dict[str, str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for project, filename in project_files.items():
        path = input_dir / filename
        if not path.exists():
            raise FileNotFoundError(path)
        df = pd.read_csv(path).fillna("")
        for column in base.REQUIRED_COLUMNS:
            if column not in df.columns:
                df[column] = ""
        df = df[base.REQUIRED_COLUMNS].copy()
        df["Source Project"] = project
        frames.append(df)
    source_df = pd.concat(frames, ignore_index=True)
    source_df["Title"] = source_df["Title"].map(base.normalize_cell)
    source_df = source_df[source_df["Title"].ne("")]
    source_df = source_df[~source_df["Title"].map(base.is_non_document_title)]
    return source_df.reset_index(drop=True)


def source_grounded_candidates(source_df: pd.DataFrame) -> pd.DataFrame:
    enriched = base.enrich_source_rows(source_df)
    standard_df, _ = base.build_integrated_standard_mdl(enriched)
    standard_df, _ = base.sort_standard_and_audit(
        standard_df,
        pd.DataFrame(columns=base.AUDIT_COLUMNS),
        "standard_no",
        "standardized_document_title",
    )
    return standard_df.reset_index(drop=True)


def assign_group(row: pd.Series) -> str:
    scope = base.normalize_cell(row.get("Scope Type"))
    text = base.normalize_key(
        " ".join(
            base.normalize_cell(row.get(column))
            for column in [
                "Standardized Document Title",
                "Sub-Sub System (Equipment)",
                "Sub-System",
                "System",
                "Source Titles",
            ]
        )
    )
    if scope == "Vendor":
        for package, markers in PACKAGE_MARKERS.items():
            if any(marker in text for marker in markers):
                return package
    if scope == "EPC":
        return "EPC"
    return ""


def candidate_payload(df: pd.DataFrame) -> list[dict[str, object]]:
    payload = []
    for _, row in df.iterrows():
        source_rows = [row]
        payload.append(
            {
                "source_standard_no": int(row["No"]),
                "discipline": base.normalize_cell(row.get("Discipline")),
                "document_type": base.normalize_cell(row.get("Document Type")),
                "system": base.normalize_cell(row.get("System")),
                "sub_system": base.normalize_cell(row.get("Sub-System")),
                "equipment": base.normalize_cell(row.get("Sub-Sub System (Equipment)")),
                "forced_system_l1": forced_system_l1(source_rows),
                "forced_sub_system_l2": forced_sub_system_l2(source_rows),
                "standardized_document_title": base.normalize_cell(row.get("Standardized Document Title")),
                "scope": base.normalize_cell(row.get("Scope Type")),
                "source_projects": base.normalize_cell(row.get("Source Projects")),
                "source_document_nos": base.normalize_cell(row.get("Source Document Nos"))[:800],
                "source_titles": base.normalize_cell(row.get("Source Titles"))[:1200],
            }
        )
    return payload


def grouped_prompt(group: str) -> str:
    section = PACKAGE_SECTION_TITLE[group]
    scope_rule = (
        f"This group must produce only {group} Vendor package documents."
        if group != "EPC"
        else "This group must produce only EPC scope documents, not vendor package detail documents."
    )
    expert_context = load_ccpp_expert_context()
    taxonomy = forced_taxonomy()
    return f"""{expert_context}

You are now using the CCPP expert context above as background knowledge for a package-grouped Standard MDL pilot.

Create the '{section}' from the provided source-grounded Standard MDL candidate rows.

Core task:
- Merge rows that mean the same deliverable.
- Keep different equipment, document purpose, subject, or scope separate.
- Rewrite document titles into concise standardized titles.
- Add missing but normally required package/scope deliverables only when the provided source rows establish the package, system, equipment, building, or EPC scope context.
- Do not target any row count.
- Do not use or assume Copilot results.
- The input rows are reference evidence, not a fixed hierarchy dictionary. Rebuild L1/L2/L3/title from source evidence when the input candidate hierarchy is weak, generic, or obviously flattened.

Group rule:
- {scope_rule}
- Vendor and EPC scope must never be mixed.
- Source-supported rows should be Source-Grounded or Source-Inferred.
- Added supplement rows must be Expert-Inferred and Needs Doosan Review.
- Every output must cite at least one source_standard_no from this batch.

Forced Level rule:
- System (L1) must use the Section 3 System taxonomy from lv1lv2강제프롬프트.docx. Do not invent new L1 names.
- Sub-System / Area (L2) must use only the Section 1 Equipment or Section 2 Building taxonomy from lv1lv2강제프롬프트.docx.
- If no Section 1 or Section 2 value is supported, set Sub-System / Area (L2) to General.
- Equipment (L3) must be a concrete equipment/object generated from L1, L2, source title evidence, and CCPP package knowledge.
- Equipment (L3) is not limited to the Section 1/2 taxonomy. Do not simply repeat L2 unless the source evidence has no more specific equipment/object.
- Remove project-specific qualifiers such as Block, Unit, Project, For Block 2, and For Block 3, 4 from Equipment (L3).
- The source rows include forced_system_l1 and forced_sub_system_l2 hints. Prefer those hints when they fit the deliverable.
- Runtime validation will normalize L1/L2 values back to these taxonomies and clean project qualifiers from L3.
- If the input candidate says things like General, Equipment Package System, Plant General System, or repeats the same value across L2/L3, treat that as weak evidence and rebuild a more concrete hierarchy from source titles.

Title rule:
- Do not force titles into a simple [L3 Equipment] + [Document Type] pattern.
- Remove project-specific qualifiers such as Block, Unit, Project, For Block 2, and For Block 3, 4 from Standardized Document Title.
- Keep the original project/block/unit wording only in Source Titles.
- If two rows differ only by block/unit/project qualifier, merge them into one standard deliverable.
- Split combined deliverables such as Data Sheet & Drawings into separate Data Sheet and Drawing rows.
- Use common abbreviations in titles, for example HRSG, ACC, DCS, GTG, STG, BOP, MOV, P&ID, I&C, MV, LV, and UPS.

Allowed System (L1) examples:
{taxonomy_text_limit(taxonomy["systems"])}

Allowed Sub-System / Area (L2) examples:
{taxonomy_text_limit(taxonomy["level2"])}

Allowed disciplines:
Civil/Structural, Mechanical, Piping, Process, Electrical, Instrumentation & Control, General.

Output structured data only."""


def run_group_batch(group: str, batch_df: pd.DataFrame) -> GroupedLLMItemList:
    user_message = (
        f"GROUP={group}\n"
        f"SECTION={PACKAGE_SECTION_TITLE[group]}\n"
        "Generate merged/standardized MDL rows for this group.\n\n"
        f"SOURCE_ROWS:\n{json.dumps(candidate_payload(batch_df), ensure_ascii=False, indent=2)}"
    )
    client = base.build_client()
    try:
        response = client.chat.completions.parse(
            model=AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": grouped_prompt(group)},
                {"role": "user", "content": user_message},
            ],
            response_format=GroupedLLMItemList,
            max_completion_tokens=12000,
        )
    except AttributeError:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": grouped_prompt(group)},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=12000,
        )
    return base.parse_structured_response(response, GroupedLLMItemList)


def iter_group_batches(group_df: pd.DataFrame, batch_size: int) -> Iterable[pd.DataFrame]:
    ordered = group_df.sort_values(
        ["Discipline", "System", "Sub-System", "Sub-Sub System (Equipment)", "Document Type", "Standardized Document Title"],
        kind="stable",
    ).reset_index(drop=True)
    for start in range(0, len(ordered), batch_size):
        yield ordered.iloc[start : start + batch_size].reset_index(drop=True)


def normalize_scope(value: object, group: str) -> str:
    if group == "EPC":
        return "EPC"
    return "Vendor"


def normalize_discipline(value: object) -> str:
    text = base.normalize_cell(value)
    if text in base.DISCIPLINE_ORDER:
        return text
    key = base.normalize_key(text)
    if "civil" in key or "struct" in key or "building" in key:
        return "Civil/Structural"
    if "pipe" in key:
        return "Piping"
    if "instrument" in key or "control" in key or "i c" in key:
        return "Instrumentation & Control"
    if "elect" in key:
        return "Electrical"
    if "process" in key:
        return "Process"
    if "mechanical" in key:
        return "Mechanical"
    return "General"


def output_row(
    item: GroupedLLMItem,
    group: str,
    source_rows: list[pd.Series],
    refs: list[int],
) -> dict[str, object]:
    evidence_type = base.normalize_cell(item.evidence_type)
    if evidence_type not in {"Source-Grounded", "Source-Inferred", "Expert-Inferred"}:
        evidence_type = "Expert-Inferred"
    review_status = base.normalize_cell(item.review_status)
    if evidence_type == "Source-Grounded" and review_status != "Needs Doosan Review":
        review_status = "Approved Source-Grounded"
    else:
        review_status = "Needs Doosan Review"
    system_l1 = forced_system_l1(source_rows, item)
    sub_system_l2 = forced_sub_system_l2(source_rows, item)
    equipment_l3 = normalize_equipment_l3(item.equipment_l3, source_rows, item)
    return {
        "No": 0,
        "Section": PACKAGE_SECTION_TITLE[group],
        "Package/Scope Group": group,
        "Discipline": normalize_discipline(item.discipline),
        "Document Type": base.normalize_cell(item.document_type) or base.majority_value(row["Document Type"] for row in source_rows),
        "System (L1)": system_l1,
        "Sub-System / Area (L2)": sub_system_l2,
        "Equipment (L3)": equipment_l3,
        "Standardized Document Title": normalize_standardized_title(item.standardized_document_title),
        "Scope": normalize_scope(item.scope, group),
        "Evidence Type": evidence_type,
        "Review Status": review_status,
        "Source Standard Nos": base.join_unique(refs),
        "Source Projects": base.join_unique_tokens(row["Source Projects"] for row in source_rows),
        "Source Document Nos": base.join_unique_tokens(row["Source Document Nos"] for row in source_rows),
        "Source Titles": base.join_unique_tokens(row["Source Titles"] for row in source_rows),
        "Generation / Merge Reason": base.normalize_cell(item.generation_merge_reason),
    }


def build_grouped_output(
    standard_df: pd.DataFrame,
    batch_size: int,
    max_epc_batches: int | None = None,
    epc_start_batch: int | None = None,
    epc_end_batch: int | None = None,
    epc_only: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = standard_df.copy()
    candidates["Package/Scope Group"] = candidates.apply(assign_group, axis=1)
    candidates = candidates[candidates["Package/Scope Group"].isin(["ACC", "HRSG", "DCS", "EPC"])].reset_index(drop=True)
    by_no = {int(row["No"]): row for _, row in candidates.iterrows()}
    output_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    rejection_rows: list[dict[str, object]] = []

    groups = ["EPC"] if epc_only else ["ACC", "HRSG", "DCS", "EPC"]
    for group in groups:
        group_df = candidates[candidates["Package/Scope Group"].eq(group)].reset_index(drop=True)
        print(f"[PACKAGE-GROUPED] group={group} candidate_rows={len(group_df)}", flush=True)
        for batch_index, batch_df in enumerate(iter_group_batches(group_df, batch_size), start=1):
            if group == "EPC" and epc_start_batch is not None and batch_index < epc_start_batch:
                continue
            if group == "EPC" and epc_end_batch is not None and batch_index > epc_end_batch:
                print(f"[PACKAGE-GROUPED] group=EPC stopped before epc_end_batch={epc_end_batch}", flush=True)
                break
            if group == "EPC" and max_epc_batches is not None and batch_index > max_epc_batches:
                print(f"[PACKAGE-GROUPED] group=EPC stopped after max_epc_batches={max_epc_batches}", flush=True)
                break
            print(f"[PACKAGE-GROUPED] group={group} batch={batch_index} rows={len(batch_df)}", flush=True)
            valid = set(batch_df["No"].astype(int).tolist())
            try:
                result = run_group_batch(group, batch_df)
            except Exception as exc:
                rejection_rows.append(
                    {
                        "group": group,
                        "batch": batch_index,
                        "source_standard_no": "",
                        "standardized_document_title": "",
                        "reason": f"llm_batch_failed:{type(exc).__name__}",
                        "raw_payload": json.dumps({"error": str(exc)[:2000], "valid_nos": sorted(valid)}, ensure_ascii=False),
                    }
                )
                continue
            for item in result.items:
                raw = item.model_dump()
                refs = [int(no) for no in item.source_standard_nos if int(no) in valid]
                invalid = [int(no) for no in item.source_standard_nos if int(no) not in valid]
                if invalid:
                    rejection_rows.append(
                        {
                            "group": group,
                            "batch": batch_index,
                            "source_standard_no": base.join_unique(invalid),
                            "standardized_document_title": base.normalize_cell(item.standardized_document_title),
                            "reason": "invalid_source_standard_no",
                            "raw_payload": json.dumps(raw, ensure_ascii=False, sort_keys=True),
                        }
                    )
                if not refs or not base.normalize_cell(item.standardized_document_title):
                    rejection_rows.append(
                        {
                            "group": group,
                            "batch": batch_index,
                            "source_standard_no": base.join_unique(item.source_standard_nos),
                            "standardized_document_title": base.normalize_cell(item.standardized_document_title),
                            "reason": "missing_valid_refs_or_title",
                            "raw_payload": json.dumps(raw, ensure_ascii=False, sort_keys=True),
                        }
                    )
                    continue
                source_rows = [by_no[no] for no in refs]
                row = output_row(item, group, source_rows, refs)
                output_rows.append(row)
                output_no = len(output_rows)
                for no in refs:
                    source = by_no[no]
                    audit_rows.append(
                        {
                            "output_no": output_no,
                            "section": row["Section"],
                            "standardized_document_title": row["Standardized Document Title"],
                            "source_standard_no": no,
                            "source_projects": base.normalize_cell(source["Source Projects"]),
                            "source_document_nos": base.normalize_cell(source["Source Document Nos"]),
                            "source_titles": base.normalize_cell(source["Source Titles"]),
                            "llm_reason": row["Generation / Merge Reason"],
                        }
                    )

    output_df = pd.DataFrame(output_rows, columns=FLAT_COLUMNS)
    if not output_df.empty:
        output_df = split_composite_deliverable_rows(output_df)
        output_df = consolidate_output(output_df)
    audit_df = pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS)
    rejection_df = pd.DataFrame(rejection_rows, columns=REJECTION_COLUMNS)
    return output_df, audit_df, rejection_df


def consolidate_output(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, group in df.groupby(["Section", "Standardized Document Title", "Scope"], sort=True, dropna=False):
        representative = group.iloc[0]
        synthetic_source_rows = [
            pd.Series(
                {
                    "System": base.choose_context_value(group["System (L1)"]),
                    "Sub-System": base.choose_context_value(group["Sub-System / Area (L2)"]),
                    "Sub-Sub System (Equipment)": base.choose_context_value(group["Equipment (L3)"]),
                    "Standardized Document Title": representative["Standardized Document Title"],
                    "Source Titles": base.join_unique_tokens(group["Source Titles"]),
                    "Document Type": base.majority_value(group["Document Type"]),
                }
            )
        ]
        rows.append(
            {
                "No": len(rows) + 1,
                "Section": representative["Section"],
                "Package/Scope Group": representative["Package/Scope Group"],
                "Discipline": base.majority_value(group["Discipline"]),
                "Document Type": base.majority_value(group["Document Type"]),
                "System (L1)": forced_system_l1(synthetic_source_rows),
                "Sub-System / Area (L2)": forced_sub_system_l2(synthetic_source_rows),
                "Equipment (L3)": normalize_equipment_l3(base.choose_context_value(group["Equipment (L3)"]), synthetic_source_rows),
                "Standardized Document Title": normalize_standardized_title(representative["Standardized Document Title"]),
                "Scope": representative["Scope"],
                "Evidence Type": combine_evidence(group["Evidence Type"]),
                "Review Status": combine_review_status(group["Review Status"]),
                "Source Standard Nos": base.join_unique_tokens(group["Source Standard Nos"]),
                "Source Projects": base.join_unique_tokens(group["Source Projects"]),
                "Source Document Nos": base.join_unique_tokens(group["Source Document Nos"]),
                "Source Titles": base.join_unique_tokens(group["Source Titles"]),
                "Generation / Merge Reason": base.join_unique_tokens(group["Generation / Merge Reason"]),
            }
        )
    output = pd.DataFrame(rows, columns=FLAT_COLUMNS)
    output["_section_order"] = output["Package/Scope Group"].map({"ACC": 0, "HRSG": 1, "DCS": 2, "EPC": 3})
    output["_discipline_order"] = output["Discipline"].map(base.order_index(base.DISCIPLINE_ORDER))
    output["_title_key"] = output["Standardized Document Title"].map(base.normalize_key)
    output = output.sort_values(["_section_order", "_discipline_order", "System (L1)", "Sub-System / Area (L2)", "Equipment (L3)", "_title_key"], kind="stable")
    output["No"] = range(1, len(output) + 1)
    return output[FLAT_COLUMNS].reset_index(drop=True)


def combine_evidence(values: Iterable[object]) -> str:
    priority = ["Expert-Inferred", "Source-Inferred", "Source-Grounded"]
    observed = {base.normalize_cell(value) for value in values}
    for value in priority:
        if value in observed:
            return value
    return base.majority_value(values)


def combine_review_status(values: Iterable[object]) -> str:
    observed = {base.normalize_cell(value) for value in values}
    if "Needs Doosan Review" in observed:
        return "Needs Doosan Review"
    return "Approved Source-Grounded"


def validation_report(df: pd.DataFrame, rejections: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if df.empty:
        rows.append(validation_row("Empty Output", "error", "", "No rows were generated."))
    duplicate_count = int(df.groupby(["Section", "Standardized Document Title", "Scope"], dropna=False).size().gt(1).sum()) if not df.empty else 0
    if duplicate_count:
        rows.append(validation_row("Duplicate Title", "error", "", f"{duplicate_count} duplicate title/scope groups remain."))
    if not rejections.empty:
        rows.append(validation_row("LLM Rejections", "review", "", f"{len(rejections)} rejection rows were created."))
    invalid_scope = int((~df["Scope"].isin(["Vendor", "EPC"])).sum()) if not df.empty else 0
    if invalid_scope:
        rows.append(validation_row("Invalid Scope", "error", "", f"{invalid_scope} rows have invalid scope."))
    taxonomy = forced_taxonomy()
    allowed_systems = set(taxonomy["systems"])  # type: ignore[arg-type]
    allowed_level2 = set(taxonomy["level2"])  # type: ignore[arg-type]
    invalid_system = int((~df["System (L1)"].isin(allowed_systems)).sum()) if not df.empty else 0
    if invalid_system:
        rows.append(validation_row("Invalid Forced System L1", "error", "", f"{invalid_system} rows are outside Section 3 System taxonomy."))
    invalid_level2 = int((~df["Sub-System / Area (L2)"].isin(allowed_level2)).sum()) if not df.empty else 0
    if invalid_level2:
        rows.append(validation_row("Invalid Forced Sub-System L2", "error", "", f"{invalid_level2} rows are outside Section 1/2 Equipment/Building taxonomy."))
    qualifier_pattern = r"For Block|Block\s+\d|For Unit|Unit\s+\d|For Project"
    l3_qualifier = int(df["Equipment (L3)"].astype(str).str.contains(qualifier_pattern, case=False, regex=True, na=False).sum()) if not df.empty else 0
    if l3_qualifier:
        rows.append(validation_row("Project Qualifier In L3", "error", "", f"{l3_qualifier} rows retain project/block/unit qualifiers in L3."))
    title_qualifier = int(df["Standardized Document Title"].astype(str).str.contains(qualifier_pattern, case=False, regex=True, na=False).sum()) if not df.empty else 0
    if title_qualifier:
        rows.append(validation_row("Project Qualifier In Title", "error", "", f"{title_qualifier} rows retain project/block/unit qualifiers in standardized title."))
    return pd.DataFrame(rows, columns=base.VALIDATION_COLUMNS)


def validation_row(kind: str, severity: str, title: str, reason: str) -> dict[str, object]:
    return {
        "validation_type": kind,
        "severity": severity,
        "discipline": "",
        "scope_type": "",
        "system": "",
        "sub_system": "",
        "equipment": "",
        "document_type": "",
        "standardized_document_title": title,
        "reason": reason,
        "recommended_action": "Review pilot output before using it as a Standard MDL baseline.",
    }


def sectioned_sheet_rows(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[list[object]] = []
    headers = ["Discipline", "Document Type", "System (L1)", "Sub-System / Area (L2)", "Equipment (L3)", "Standardized Document Title", "Scope"]
    for group in ["ACC", "HRSG", "DCS", "EPC"]:
        section_df = df[df["Package/Scope Group"].eq(group)]
        if section_df.empty:
            continue
        rows.append([PACKAGE_SECTION_TITLE[group], "", "", "", "", "", ""])
        rows.append(headers)
        for _, row in section_df.iterrows():
            rows.append(
                [
                    row["Discipline"],
                    row["Document Type"],
                    row["System (L1)"],
                    row["Sub-System / Area (L2)"],
                    row["Equipment (L3)"],
                    row["Standardized Document Title"],
                    row["Scope"],
                ]
            )
    return pd.DataFrame(rows)


def summary_df(source_df: pd.DataFrame, candidate_df: pd.DataFrame, output_df: pd.DataFrame, rejection_df: pd.DataFrame, input_projects: str) -> pd.DataFrame:
    rows = [
        ("mode", "package_grouped_llm_pilot"),
        ("input_projects", input_projects),
        ("source_rows", len(source_df)),
        ("source_grounded_candidate_rows", len(candidate_df)),
        ("output_rows", len(output_df)),
        ("rejection_rows", len(rejection_df)),
    ]
    for group, count in output_df["Package/Scope Group"].value_counts().sort_index().items():
        rows.append((f"output_rows:{group}", count))
    for evidence, count in output_df["Evidence Type"].value_counts().sort_index().items():
        rows.append((f"evidence_type:{evidence}", count))
    for status, count in output_df["Review Status"].value_counts().sort_index().items():
        rows.append((f"review_status:{status}", count))
    return pd.DataFrame(rows, columns=base.SUMMARY_COLUMNS)


def write_outputs(
    output_dir: Path,
    source_df: pd.DataFrame,
    candidate_df: pd.DataFrame,
    output_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    rejection_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    input_projects: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summary_df(source_df, candidate_df, output_df, rejection_df, input_projects)
    output_df.to_csv(output_dir / "package_grouped_standard_mdl.csv", index=False, encoding="utf-8-sig")
    audit_df.to_csv(output_dir / "package_grouped_audit.csv", index=False, encoding="utf-8-sig")
    rejection_df.to_csv(output_dir / "package_grouped_rejections.csv", index=False, encoding="utf-8-sig")
    validation_df.to_csv(output_dir / "package_grouped_validation.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(output_dir / "package_grouped_standard_mdl.xlsx", engine="openpyxl") as writer:
        output_df.to_excel(writer, sheet_name="Flat Standard MDL", index=False)
        sectioned_sheet_rows(output_df).to_excel(writer, sheet_name="Package Grouped MDL", index=False, header=False)
        audit_df.to_excel(writer, sheet_name="Source Mapping Audit", index=False)
        validation_df.to_excel(writer, sheet_name="Validation Report", index=False)
        rejection_df.to_excel(writer, sheet_name="LLM Rejections", index=False)
        summary.to_excel(writer, sheet_name="Run Summary", index=False)


def normalize_existing_output(existing_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    output_df = pd.read_excel(existing_path, sheet_name="Flat Standard MDL").fillna("")
    for column in FLAT_COLUMNS:
        if column not in output_df.columns:
            output_df[column] = ""
    output_df = output_df[FLAT_COLUMNS].copy()
    normalized_rows: list[dict[str, object]] = []
    for _, row in output_df.iterrows():
        source_row = pd.Series(
            {
                "System": row["System (L1)"],
                "Sub-System": row["Sub-System / Area (L2)"],
                "Sub-Sub System (Equipment)": row["Equipment (L3)"],
                "Standardized Document Title": row["Standardized Document Title"],
                "Source Titles": row["Source Titles"],
                "Document Type": row["Document Type"],
            }
        )
        normalized = row.to_dict()
        normalized["System (L1)"] = forced_system_l1([source_row], extra_values=[row["Generation / Merge Reason"]])
        normalized["Sub-System / Area (L2)"] = forced_sub_system_l2([source_row], extra_values=[row["Generation / Merge Reason"]])
        normalized["Equipment (L3)"] = normalize_equipment_l3(row["Equipment (L3)"], [source_row])
        normalized["Standardized Document Title"] = normalize_standardized_title(row["Standardized Document Title"])
        normalized_rows.append(normalized)
    normalized_df = pd.DataFrame(normalized_rows, columns=FLAT_COLUMNS)
    if not normalized_df.empty:
        normalized_df = split_composite_deliverable_rows(normalized_df)
        normalized_df = consolidate_output(normalized_df)

    try:
        audit_df = pd.read_excel(existing_path, sheet_name="Source Mapping Audit").fillna("")
    except ValueError:
        audit_df = pd.DataFrame(columns=AUDIT_COLUMNS)
    for column in AUDIT_COLUMNS:
        if column not in audit_df.columns:
            audit_df[column] = ""
    audit_df = audit_df[AUDIT_COLUMNS].copy()

    try:
        rejection_df = pd.read_excel(existing_path, sheet_name="LLM Rejections").fillna("")
    except ValueError:
        rejection_df = pd.DataFrame(columns=REJECTION_COLUMNS)
    for column in REJECTION_COLUMNS:
        if column not in rejection_df.columns:
            rejection_df[column] = ""
    rejection_df = rejection_df[REJECTION_COLUMNS].copy()
    return normalized_df, audit_df, rejection_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build package-grouped LLM pilot Standard MDL.")
    parser.add_argument("--input-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--all-projects", action="store_true", help="Use all seven classified MDL projects instead of the two-project pilot.")
    parser.add_argument("--max-epc-batches", type=int, help="Limit EPC processing to the first N batches for review runs.")
    parser.add_argument("--epc-start-batch", type=int, help="Start EPC processing from this absolute batch number.")
    parser.add_argument("--epc-end-batch", type=int, help="Stop EPC processing after this absolute batch number.")
    parser.add_argument("--epc-only", action="store_true", help="Process only EPC batches, useful for continuation runs.")
    parser.add_argument("--normalize-existing", type=Path, help="Apply forced L1/L2 taxonomy to an existing package-grouped output workbook.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.normalize_existing:
        output_dir = args.output_dir
        if output_dir is None:
            output_dir = args.normalize_existing.parent.parent / f"{args.normalize_existing.parent.name}_lv1lv2_forced"
        output_df, audit_df, rejection_df = normalize_existing_output(args.normalize_existing)
        validation_df = validation_report(output_df, rejection_df)
        write_outputs(output_dir, pd.DataFrame(), pd.DataFrame(), output_df, audit_df, rejection_df, validation_df, "normalized_existing")
        print("[PACKAGE-GROUPED] normalized existing:", args.normalize_existing, flush=True)
        print("[PACKAGE-GROUPED] output rows:", len(output_df), flush=True)
        print("[PACKAGE-GROUPED] validation rows:", len(validation_df), flush=True)
        print("[PACKAGE-GROUPED] wrote:", output_dir / "package_grouped_standard_mdl.xlsx", flush=True)
        return 0

    project_files = base.PROJECT_FILES if args.all_projects else PILOT_PROJECTS
    input_projects = " | ".join(project_files.keys())
    output_dir = args.output_dir
    if output_dir is None:
        suffix = "package_grouped_llm_all_projects" if args.all_projects else "package_grouped_llm_pilot"
        output_dir = OUTPUT_DIR / "standard_mdl" / suffix
    source_df = load_source(args.input_dir, project_files)
    candidate_df = source_grounded_candidates(source_df)
    output_df, audit_df, rejection_df = build_grouped_output(
        candidate_df,
        batch_size=args.batch_size,
        max_epc_batches=args.max_epc_batches,
        epc_start_batch=args.epc_start_batch,
        epc_end_batch=args.epc_end_batch,
        epc_only=args.epc_only,
    )
    validation_df = validation_report(output_df, rejection_df)
    write_outputs(output_dir, source_df, candidate_df, output_df, audit_df, rejection_df, validation_df, input_projects)
    print("[PACKAGE-GROUPED] source rows:", len(source_df), flush=True)
    print("[PACKAGE-GROUPED] candidate rows:", len(candidate_df), flush=True)
    print("[PACKAGE-GROUPED] output rows:", len(output_df), flush=True)
    print("[PACKAGE-GROUPED] rejections:", len(rejection_df), flush=True)
    print("[PACKAGE-GROUPED] wrote:", output_dir / "package_grouped_standard_mdl.xlsx", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
