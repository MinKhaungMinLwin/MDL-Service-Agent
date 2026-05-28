"""Compute FA/FC date ranges from a parsed VT formula and an anchor date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

_FC_DEFAULT_AFTER_FA_DAYS = 60
_FC_DEFAULT_WINDOW_DAYS = 30


@dataclass
class DateRange:
    fa_earliest: date | None = None
    fa_latest: date | None = None
    fa_recommended: date | None = None
    fc_earliest: date | None = None
    fc_latest: date | None = None
    fc_recommended: date | None = None
    sub_type: str = "UNKNOWN"
    confidence: float = 0.0
    notes: str = ""


def compute_date_range(
    vt_parsed: dict,
    anchor_date: date | None,
    sub_type: str,
    priority: int,
) -> DateRange:
    """Compute FA/FC date ranges from a parsed VT formula and anchor date.

    Args:
        vt_parsed:   Output of vt_parser.parse_validation_time().
        anchor_date: The resolved base date (activity start/finish).
        sub_type:    FA / FC / FI / SKIP from validation rule.
        priority:    Rule priority (1=most specific, determines confidence).
    """
    result = DateRange(sub_type=sub_type)

    if sub_type == "SKIP":
        result.notes = "Document excluded from scheduling"
        return result

    if not vt_parsed.get("valid"):
        result.notes = f"No valid VT formula: {vt_parsed.get('raw', '')}"
        return result

    if anchor_date is None:
        result.notes = "Missing anchor date — cannot compute range"
        return result

    if vt_parsed.get("has_fa_rule"):
        fa_lo = _offset(anchor_date, vt_parsed["fa_lo_days"])
        fa_hi = _offset(anchor_date, vt_parsed["fa_hi_days"])
        result.fa_earliest = fa_lo
        result.fa_latest = fa_hi
        result.fa_recommended = _midpoint(fa_lo, fa_hi)

    if vt_parsed.get("has_fc_rule"):
        fc_lo = _offset(anchor_date, vt_parsed["fc_lo_days"])
        fc_hi = _offset(anchor_date, vt_parsed["fc_hi_days"])
        result.fc_earliest = fc_lo
        result.fc_latest = fc_hi
        result.fc_recommended = _midpoint(fc_lo, fc_hi)
    elif result.fa_recommended is not None:
        # Default FC = FA recommended + 2 months ± 2 weeks
        fc_center = _offset(result.fa_recommended, _FC_DEFAULT_AFTER_FA_DAYS)
        result.fc_earliest = _offset(fc_center, -_FC_DEFAULT_WINDOW_DAYS // 2)
        result.fc_latest = _offset(fc_center, _FC_DEFAULT_WINDOW_DAYS // 2)
        result.fc_recommended = fc_center

    result.confidence = {1: 0.9, 2: 0.6, 3: 0.3}.get(priority, 0.2)
    return result


def _offset(base: date, days: int) -> date:
    return base + timedelta(days=days)


def _midpoint(d1: date, d2: date) -> date:
    return d1 + (d2 - d1) / 2
