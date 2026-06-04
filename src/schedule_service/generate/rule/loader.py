"""Parse the validation-rule CSV into ValidationRule objects."""

from __future__ import annotations

import csv
from pathlib import Path

from schedule_service.generate.rule.models import ValidationRule
from schedule_service.generate.rule.vt_parser import parse_validation_time

DEFAULT_RULE_PATH = Path("data/schedule_service/processed/validation_rule_clean.csv")

_SUB_TYPE_MAP: dict[str, str] = {
    "fa": "FA",
    "ap": "FA",
    "ap: for approval": "FA",
    "fa/fi": "FA",
    "fi": "FI",
    "if": "FI",
    "ifi": "FI",
    "ifr": "FI",
    "if : for information": "FI",
    "as built": "SKIP",
    "unmatch": "SKIP",
}


def load_rules(path: Path = DEFAULT_RULE_PATH) -> list[ValidationRule]:
    """Load validation rules from a semicolon-delimited CSV (in CSV order)."""
    rules: list[ValidationRule] = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            priority_raw = row.get("Priority", "").strip()
            if not priority_raw or not priority_raw.isdigit():
                continue
            doc_kw = row.get("MDL Document Keyword", "").strip()
            if not doc_kw:
                continue
            sub_type_raw = row.get("Pur.", "").strip().lower()
            vt_raw = row.get("Validation Time", "").strip()
            if sub_type_raw in _SUB_TYPE_MAP:
                sub_type = _SUB_TYPE_MAP[sub_type_raw]
            elif not sub_type_raw:
                # Pur. is empty — infer from VT formula instead of defaulting to SKIP.
                # 2896 rules have empty Pur. but valid FA/FC formulas in the CSV.
                vt_temp = parse_validation_time(vt_raw)
                sub_type = "FA" if vt_temp.get("has_fa_rule") or vt_temp.get("has_fc_rule") else "SKIP"
            else:
                sub_type = "SKIP"
            act_kws = [k.strip() for k in row.get("Activity Keyword", "").split("|") if k.strip()]
            raw_item = row.get("Item", "").replace("\xa0", " ").strip()
            rules.append(
                ValidationRule(
                    priority=int(priority_raw),
                    item_name=raw_item,
                    doc_keyword=doc_kw,
                    activity_keywords=act_kws,
                    sub_type=sub_type,
                    vt_parsed=parse_validation_time(vt_raw),
                )
            )
    return rules
