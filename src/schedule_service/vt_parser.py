"""Parse Validation Time formula strings into structured date offset dicts.

Formula examples from validation_rule.csv:
  start+4W<=FA<=start+4W+2M
  start-4M-2M<=FA<=start-4M
  start+8W<=FA<=FC<=start+20W
  start-3M<=FC<=start-1M
  -   (no rule)
"""

from __future__ import annotations

import re

_UNIT_DAYS: dict[str, float] = {"d": 1, "w": 7, "m": 30, "y": 365}
_TERM_RE = re.compile(r"([+-])\s*(\d+(?:\.\d+)?)\s*([DWMYdwmy]m?)")


def _to_days(value: float, unit: str) -> int:
    return round(value * _UNIT_DAYS[unit.lower()])


def _parse_offset_terms(expr: str) -> int:
    total = 0
    for sign, value, unit in _TERM_RE.findall(expr):
        days = _to_days(float(value), unit)
        total += days if sign == "+" else -days
    return total


def _normalize(formula: str) -> str:
    formula = re.sub(r"\s+", "", formula.strip())
    formula = re.sub(r"(?i)\bstart\b", "start", formula)
    formula = re.sub(r"(?i)\bfinish\b", "finish", formula)
    return formula.replace("=<", "<=")


_ANCHOR = r"(start|finish)"
_TERMS = r"((?:[+-]\d+(?:\.\d+)?[DWMYdwmy]m?)+)"
_LEQ = r"<="


def _parse_anchor_offset(expr: str) -> tuple[str, int]:
    m = re.fullmatch(_ANCHOR + r"((?:[+-]\d+(?:\.\d+)?[DWMYdwmy]m?)*)", expr)
    if not m:
        raise ValueError(f"Cannot parse anchor+offset: {expr!r}")
    offset = _parse_offset_terms(m.group(2)) if m.group(2) else 0
    return m.group(1), offset


def parse_validation_time(formula: str) -> dict:
    """Return structured dict with FA/FC day offsets from anchor date."""
    raw = formula.strip()
    base = {
        "raw": raw,
        "valid": False,
        "anchor": "start",
        "fa_lo_days": None,
        "fa_hi_days": None,
        "fc_lo_days": None,
        "fc_hi_days": None,
        "has_fa_rule": False,
        "has_fc_rule": False,
    }
    if raw in ("-", "", "Unmatch"):
        return base

    f = _normalize(raw)

    # FA<=FC joint: start+8W<=FA<=FC<=start+20W
    m = re.fullmatch(_ANCHOR + _TERMS + _LEQ + r"FA" + _LEQ + r"FC" + _LEQ + _ANCHOR + _TERMS, f, re.IGNORECASE)
    if m:
        anchor_lo, lo = _parse_anchor_offset(m.group(1) + m.group(2))
        anchor_hi, hi = _parse_anchor_offset(m.group(3) + m.group(4))
        return {
            **base,
            "valid": True,
            "anchor": anchor_lo,
            "fa_lo_days": lo,
            "fa_hi_days": hi,
            "fc_lo_days": lo,
            "fc_hi_days": hi,
            "has_fa_rule": True,
            "has_fc_rule": True,
        }

    # FC-only: start+3M<=FC<=start+5M
    m = re.fullmatch(_ANCHOR + _TERMS + _LEQ + r"FC" + _LEQ + _ANCHOR + _TERMS, f, re.IGNORECASE)
    if m:
        anchor_lo, lo = _parse_anchor_offset(m.group(1) + m.group(2))
        anchor_hi, hi = _parse_anchor_offset(m.group(3) + m.group(4))
        return {**base, "valid": True, "anchor": anchor_lo, "fc_lo_days": lo, "fc_hi_days": hi, "has_fc_rule": True}

    # FA with bounds: start+4W<=FA<=start+6W
    m = re.fullmatch(_ANCHOR + _TERMS + _LEQ + r"FA" + _LEQ + _ANCHOR + _TERMS, f, re.IGNORECASE)
    if m:
        anchor_lo, lo = _parse_anchor_offset(m.group(1) + m.group(2))
        anchor_hi, hi = _parse_anchor_offset(m.group(3) + m.group(4))
        return {**base, "valid": True, "anchor": anchor_lo, "fa_lo_days": lo, "fa_hi_days": hi, "has_fa_rule": True}

    # FA with strict <
    m = re.fullmatch(
        _ANCHOR + _TERMS + _LEQ + r"FA" + _LEQ + _ANCHOR + _TERMS, f.replace("<=FA<", "<=FA<="), re.IGNORECASE
    )
    if m:
        anchor_lo, lo = _parse_anchor_offset(m.group(1) + m.group(2))
        anchor_hi, hi = _parse_anchor_offset(m.group(3) + m.group(4))
        return {**base, "valid": True, "anchor": anchor_lo, "fa_lo_days": lo, "fa_hi_days": hi, "has_fa_rule": True}

    # FA with no lower offset: start<=FA<=start+2M
    m = re.fullmatch(r"(start|finish)" + _LEQ + r"FA" + _LEQ + _ANCHOR + _TERMS, f, re.IGNORECASE)
    if m:
        anchor_hi, hi = _parse_anchor_offset(m.group(2) + m.group(3))
        return {**base, "valid": True, "anchor": m.group(1), "fa_lo_days": 0, "fa_hi_days": hi, "has_fa_rule": True}

    # Multi-line: take first line
    if "\n" in raw:
        return parse_validation_time(raw.split("\n")[0].strip())

    return base


def describe(parsed: dict) -> str:
    if not parsed["valid"]:
        return f"No rule ({parsed['raw']})"
    anchor = parsed["anchor"]
    parts = []
    if parsed["has_fa_rule"]:
        parts.append(f"FA ∈ [{anchor}{parsed['fa_lo_days']:+d}d, {anchor}{parsed['fa_hi_days']:+d}d]")
    if parsed["has_fc_rule"]:
        parts.append(f"FC ∈ [{anchor}{parsed['fc_lo_days']:+d}d, {anchor}{parsed['fc_hi_days']:+d}d]")
    return "  |  ".join(parts)
