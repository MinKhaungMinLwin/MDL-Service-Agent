"""Compute FA/FC date ranges from a parsed VT formula and an anchor date."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

_FC_DEFAULT_AFTER_FA_DAYS = 60
_FC_DEFAULT_WINDOW_DAYS = 30
# Minimum days between fa_recommended and fc_earliest (guards chained VT formulas
# like "start+2W<=FA<=FC<=start+12W" which the parser assigns identical windows to both)
_MIN_FA_FC_GAP_DAYS = 21


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
    # Names of date fields that the NTP floor clamped (their template value fell before
    # the project NTP). A clamped recommended date means the date is fabricated at the
    # floor, not a genuine schedule position.
    floored_fields: list[str] = field(default_factory=list)

    @property
    def is_floored_degenerate(self) -> bool:
        """True when NTP flooring fabricated/collapsed the recommended submission date.

        The template places this document before the project NTP (negative-offset VT
        anchored near NTP), so the floor either clamps the recommended date or collapses
        the whole window to a single day. The resulting range is not a real schedule.
        """
        if self.fa_recommended is not None:
            return "fa_recommended" in self.floored_fields or (
                self.fa_earliest is not None and self.fa_earliest == self.fa_latest
            )
        # For-information / FC-only outputs: judge the FC window instead.
        if self.fc_recommended is not None:
            return "fc_recommended" in self.floored_fields or (
                self.fc_earliest is not None and self.fc_earliest == self.fc_latest
            )
        return False


def compute_date_range(
    vt_parsed: dict,
    anchor_date: date | None,
    sub_type: str,
    priority: int,
    ntp_floor: date | None = None,
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

    # FC-only rules with FA submission type: derive FA window from FC.
    # The VT formula constrains when FC must be submitted (before an activity starts).
    # FA precedes FC by the standard review gap, so FA is back-calculated from FC.
    if result.fc_recommended is not None and result.fa_recommended is None and sub_type == "FA":
        fa_center = _offset(result.fc_recommended, -_FC_DEFAULT_AFTER_FA_DAYS)
        fa_window = _FC_DEFAULT_WINDOW_DAYS // 2
        result.fa_earliest = _offset(fa_center, -fa_window)
        result.fa_latest = _offset(fa_center, fa_window)
        result.fa_recommended = fa_center
        result.notes = "FA derived from FC constraint (FC-only VT rule)"

    result.confidence = {1: 0.9, 2: 0.6, 3: 0.3}.get(priority, 0.2)

    # Enforce minimum FA→FC gap: guards chained VT formulas with identical windows
    if result.fa_recommended is not None and result.fc_earliest is not None:
        min_fc_start = result.fa_recommended + timedelta(days=_MIN_FA_FC_GAP_DAYS)
        if result.fc_earliest < min_fc_start:
            shift = (min_fc_start - result.fc_earliest).days
            result.fc_earliest = result.fc_earliest + timedelta(days=shift)
            if result.fc_recommended is not None:
                result.fc_recommended = result.fc_recommended + timedelta(days=shift)
            if result.fc_latest is not None:
                result.fc_latest = result.fc_latest + timedelta(days=shift)

    if ntp_floor is not None:
        for field_name in ("fa_earliest", "fa_recommended", "fa_latest",
                           "fc_earliest", "fc_recommended", "fc_latest"):
            val = getattr(result, field_name)
            if val is not None and val < ntp_floor:
                setattr(result, field_name, ntp_floor)
                result.floored_fields.append(field_name)

    return result


def _offset(base: date, days: int) -> date:
    return base + timedelta(days=days)


def _midpoint(d1: date, d2: date) -> date:
    return d1 + (d2 - d1) / 2
