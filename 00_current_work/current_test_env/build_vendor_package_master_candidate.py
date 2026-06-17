"""Build a reviewable vendor package master candidate from classified MDLs.

This script aggregates raw Equipment values across the seven classified MDL CSVs,
normalizes obvious noise, maps rows into canonical vendor package groups where
possible, and leaves ambiguous values in a Review Needed bucket for human review.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

import build_standard_mdl as base
from mdl_runtime.config import OUTPUT_DIR


OUTPUT_COLUMNS = [
    "raw_equipment",
    "canonical_raw_equipment",
    "canonical_package",
    "canonical_equipment_name",
    "vendor_section_title",
    "raw_count",
    "project_count",
    "source_projects",
    "review_status",
    "mapping_reason",
]

SUMMARY_COLUMNS = ["canonical_package", "raw_count", "unique_raw_values", "project_count"]

EXCLUDED_PACKAGES = {
    "ACC",
    "HRSG",
    "DCS",
    "Balance of Plant",
}

PACKAGE_RULES: list[tuple[str, str, list[str]]] = [
    ("GT / GTG", "GT Vendor Document List", [r"gas turbine", r"\bgt\b", r"gtg"]),
    ("ST / STG", "ST/STG Vendor Document List", [r"steam turbine", r"\bst\b", r"stg", r"steam turbine generator"]),
    ("Pump", "Pump Vendor Document List", [r"\bpump\b", r"\bbfp\b", r"\bcep\b", r"\bcwp\b", r"\bccwp\b", r"vacuum pump", r"feed water pump", r"boiler feed pump"]),
    ("Tank", "Tank Vendor Document List", [r"\btank\b", r"deaerator"]),
    ("Air / Gas Package", "Air/Gas Package Vendor Document List", [r"air compressor", r"compressed air", r"fuel gas compressor", r"fuel gas conditioning", r"gas treatment", r"hydrogen generation", r"industrial gas"]),
    ("Boiler / Heater / Cooler", "Boiler/Cooler Vendor Document List", [r"boiler", r"fin fan cooler", r"air cooled heat exchanger", r"heat exchanger", r"\bache\b"]),
    ("Electrical Major Equipment", "Electrical Major Equipment Vendor Document List", [r"transformer", r"switchgear", r"generator circuit breaker", r"\bgcb\b", r"\bgis\b", r"air insulated switchgear", r"motor control center", r"\bmcc\b", r"\bups\b", r"\bdc system\b", r"\bipbd\b", r"\bipb\b", r"phase bus", r"\bais\b"]),
    ("Water Treatment Package", "Water Treatment Vendor Document List", [r"water treatment", r"waste water", r"\betp\b", r"\bswas\b", r"\bstp\b", r"\bows\b"]),
    ("Diesel Generator Package", "Diesel Generator Vendor Document List", [r"blackstart diesel generator", r"emergency diesel generator", r"\bbsedg\b", r"\bedg\b", r"diesel generator"]),
    ("Cooling Tower Package", "Cooling Tower Vendor Document List", [r"cooling tower"]),
    ("Condenser / CTCS", "Condenser Vendor Document List", [r"condenser tube cleaning", r"^condenser$", r"water box vacuum pump", r"\bctcs\b"]),
    ("Crane / Hoist Package", "Crane & Hoist Vendor Document List", [r"crane", r"hoist", r"lifting device"]),
    ("Valve Package", "Valve Vendor Document List", [r"valve", r"control valve", r"prds", r"safety relief valve", r"\bmov\b"]),
    ("Instrument / Protection Package", "Instrument/Protection Vendor Document List", [r"field instrument", r"protection panel", r"telecommunication panel", r"\bfms\b", r"closed circuit television", r"\bcctv\b"]),
    ("Cable / Tray Package", "Cable Vendor Document List", [r"cable tray", r"\bcable\b", r"cable termination", r"cable raceway", r"fiber optic"]),
]


def remove_project_qualifiers(text: object) -> str:
    value = base.normalize_cell(text)
    if not value:
        return ""
    value = re.sub(r"\s*\((?:[^)]*for\s+)?block[^)]*\)", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*\((?:[^)]*for\s+)?unit[^)]*\)", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*\((?:[^)]*for\s+)?project[^)]*\)", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\(V\)|（V）|\[V\]", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\[[^\]]+\]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" _-/,")
    return base.normalize_cell(value)


def canonical_equipment_name(raw_value: str) -> str:
    value = remove_project_qualifiers(raw_value)
    replacements = [
        (r"\bGas Turbine Generator\b", "GTG"),
        (r"\bSteam Turbine Generator\b", "STG"),
        (r"\bGenerator Step[- ]Up Transformer\b", "GSUT"),
        (r"\bGenerator Circuit Breaker\b", "GCB"),
        (r"\bMotor Control Center\b", "MCC"),
        (r"\bPiping Specialties\b", "Piping Specialties"),
        (r"\bCondensate Extraction Pump\b", "CEP"),
        (r"\bBoiler Feed Pump\b", "BFP"),
        (r"\bClosed Cooling Water Pump\b", "CCWP"),
        (r"\bCirculating Water Pump\b", "CWP"),
        (r"\bWater Box Vacuum Pump\b", "WBVP"),
        (r"\bCondenser Vacuum Pump\b", "CVP"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return base.normalize_cell(value)


def excluded(value: str) -> bool:
    key = base.normalize_key(remove_project_qualifiers(value))
    return key in {
        base.normalize_key("ACC"),
        base.normalize_key("Air Cooled Condenser"),
        base.normalize_key("HRSG"),
        base.normalize_key("Heat Recovery Steam Generator"),
        base.normalize_key("DCS"),
        base.normalize_key("Balance of Plant"),
        base.normalize_key("BOP"),
    }


def map_package(value: str) -> tuple[str, str, str]:
    canonical_value = canonical_equipment_name(value)
    key = base.normalize_key(canonical_value)
    for package, section, patterns in PACKAGE_RULES:
        for pattern in patterns:
            if re.search(pattern, key, flags=re.IGNORECASE):
                return package, section, "mapped_by_rule"
    return "Review Needed", "", "needs_review"


def load_source(input_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for project, filename in base.PROJECT_FILES.items():
        path = input_dir / filename
        df = pd.read_csv(path).fillna("")
        df["Source Project"] = project
        frames.append(df)
    source_df = pd.concat(frames, ignore_index=True)
    source_df["Equipment"] = source_df["Equipment"].map(base.normalize_cell)
    return source_df[source_df["Equipment"].ne("")].reset_index(drop=True)


def build_master(source_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    grouped = source_df.groupby("Equipment", dropna=False)
    for raw_equipment, group in grouped:
        raw_equipment = base.normalize_cell(raw_equipment)
        if not raw_equipment or excluded(raw_equipment):
            continue
        canonical_raw = canonical_equipment_name(raw_equipment)
        canonical_package, vendor_section_title, mapping_reason = map_package(raw_equipment)
        review_status = "Mapped" if canonical_package != "Review Needed" else "Needs Review"
        rows.append(
            {
                "raw_equipment": raw_equipment,
                "canonical_raw_equipment": canonical_raw,
                "canonical_package": canonical_package,
                "canonical_equipment_name": canonical_raw,
                "vendor_section_title": vendor_section_title,
                "raw_count": len(group),
                "project_count": group["Source Project"].nunique(),
                "source_projects": base.join_unique(group["Source Project"]),
                "review_status": review_status,
                "mapping_reason": mapping_reason,
            }
        )
    master = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    master["_package_key"] = master["canonical_package"].map(base.normalize_key)
    master["_mapped_order"] = master["review_status"].eq("Needs Review").astype(int)
    master["_count_order"] = -master["raw_count"]
    master["_raw_key"] = master["canonical_raw_equipment"].map(base.normalize_key)
    master = master.sort_values(["_mapped_order", "_package_key", "_count_order", "_raw_key"], kind="stable")
    return master[OUTPUT_COLUMNS].reset_index(drop=True)


def build_summary(master: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        master.groupby("canonical_package", dropna=False)
        .agg(
            raw_count=("raw_count", "sum"),
            unique_raw_values=("raw_equipment", "nunique"),
            project_count=("project_count", "max"),
        )
        .reset_index()
        .sort_values(["raw_count", "unique_raw_values"], ascending=[False, False], kind="stable")
    )
    return grouped[SUMMARY_COLUMNS]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build vendor package master candidate from classified MDLs.")
    parser.add_argument("--input-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR / "standard_mdl" / "vendor_package_master_candidate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_df = load_source(args.input_dir)
    master_df = build_master(source_df)
    summary_df = build_summary(master_df)
    review_df = master_df[master_df["review_status"].eq("Needs Review")].reset_index(drop=True)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    master_df.to_csv(args.output_dir / "vendor_package_master_candidate.csv", index=False, encoding="utf-8-sig")
    review_df.to_csv(args.output_dir / "vendor_package_master_review_needed.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(args.output_dir / "vendor_package_master_candidate.xlsx", engine="openpyxl") as writer:
        master_df.to_excel(writer, sheet_name="Master Candidate", index=False)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        review_df.to_excel(writer, sheet_name="Review Needed", index=False)

    print("[VENDOR-PACKAGE] source equipment rows:", len(source_df), flush=True)
    print("[VENDOR-PACKAGE] master candidate rows:", len(master_df), flush=True)
    print("[VENDOR-PACKAGE] review needed rows:", len(review_df), flush=True)
    print("[VENDOR-PACKAGE] wrote:", args.output_dir / "vendor_package_master_candidate.xlsx", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
