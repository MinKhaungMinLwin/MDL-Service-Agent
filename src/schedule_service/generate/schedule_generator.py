"""Generate FA/FC date ranges from MDL classified documents.

Thin orchestration only: read the CSV, resolve a validation rule and a CCPP activity for
every row (delegated to rule.matcher / activity.matcher), compute date ranges, and write
the output. All matching logic lives in the rule/ and activity/ subpackages.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from loguru import logger

from schedule_service.generate._shared.resource_cache import (
    get_activity_semantic_index,
    get_bm25_index,
    get_rule_matcher,
    get_rule_semantic_index,
    get_structured_activity_index,
)
from schedule_service.generate.activity.loader import DEFAULT_SCHEDULE_PATH, load_schedule_activities
from schedule_service.generate.activity.matcher import (
    ActivityMatchQuality,
    _activity_phase,
    _scope_keys,
    resolve_activity_matches,
    resolve_anchor_date,
)
from schedule_service.generate.activity.models import ScheduleActivity
from schedule_service.generate.date.date_range_engine import DateRange, compute_date_range
from schedule_service.generate.rule.generic_judge import (
    GenericVerdict,
    JudgeProvider,
    resolve_generic_verdicts,
)
from schedule_service.generate.rule.loader import DEFAULT_RULE_PATH
from schedule_service.generate.rule.matcher import RuleMatchQuality, build_rule_query, resolve_rule_matches
from schedule_service.generate.rule.models import ValidationRule
from schedule_service.output_writer import write_schedule_outputs

DEFAULT_OUTPUT_DIR = Path("output/schedule_service/generate")

# All dates in the CCPP guide schedule are relative to this template NTP.
TEMPLATE_NTP = date(2007, 3, 1)


@dataclass(frozen=True)
class MatchContext:
    """The validation rule and CCPP guide schedule activity resolved for one MDL row."""

    rule: ValidationRule | None
    activity: ScheduleActivity
    rule_quality: RuleMatchQuality | None = None
    activity_quality: ActivityMatchQuality | None = None
    rule_generic_verdict: GenericVerdict | None = None


def generate_schedule_file(
    input_csv: Path,
    schedule_activities: list[ScheduleActivity],
    output_dir: Path,
    rule_path: Path = DEFAULT_RULE_PATH,
    limit: int = 0,
    ntp_date: str = "",
    semantic_cache_dir: Path | None = None,
    semantic_weight: float = 0.3,
    activity_cache_dir: Path | None = None,
    activity_resolver: str = "text",
    rule_generic_judge: JudgeProvider | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Generate FA/FC date ranges from an MDL classified CSV.

    Returns (xlsx_path, json_path, timing) where timing breaks down each processing phase.
    Always uses hybrid (token + semantic) scoring for rule matching and BM25 + semantic + RRF for activity matching.

    Args:
        ntp_date:             Real project NTP date in ISO format (e.g. "2024-01-15").
                              Shifts all guide schedule template dates accordingly.
        semantic_cache_dir:   Path to semantic cache directory for rule embeddings.
        semantic_weight:      Weight of semantic score in hybrid rule scoring (0–1, default 0.3).
        activity_cache_dir:   Path to semantic cache directory for activity embeddings.
    """
    import time

    t0 = time.perf_counter()

    _log(f"Reading MDL classified CSV: {input_csv}")
    rows = _read_csv(input_csv)
    original_count = len(rows)
    rows, candidate_filter = _filter_schedulable_candidates(rows)
    if limit > 0:
        rows = rows[:limit]
        _log(f"Limit enabled: processing first {len(rows)} accepted rows from {original_count} input rows")
    if not rows:
        raise ValueError(f"No schedulable rows found in {input_csv}")

    t_read = time.perf_counter()

    shift_days = _compute_shift(ntp_date)
    if shift_days:
        _log(f"NTP shift: {ntp_date} → {shift_days:+d} days from template NTP {TEMPLATE_NTP}")
    else:
        _log("No NTP date provided — using guide schedule template dates")

    rule_matcher = get_rule_matcher(rule_path)
    bm25 = get_bm25_index(schedule_activities)

    t_load = time.perf_counter()

    # 1. Resolve the validation rule for every row (always hybrid token + semantic).
    rule_semantic_index = get_rule_semantic_index(rule_matcher, semantic_cache_dir) if rule_matcher else None
    rules, rule_qualities = resolve_rule_matches(rows, rule_matcher, rule_semantic_index, semantic_weight)

    # 1b. Resolve rule_generic ambiguity: deterministic bucketing for all generic-rule
    #     rows, plus an optional LLM judge for the genuinely ambiguous ones (G_AMBIG).
    if rule_matcher is not None:
        generic_verdicts = resolve_generic_verdicts(
            rows, rules, rule_qualities, rule_matcher.rules, provider=rule_generic_judge
        )
    else:
        generic_verdicts = [None] * len(rows)

    t_rules = time.perf_counter()

    # 2. Resolve the CCPP activity for every row (always BM25 + semantic + RRF), rule-boosted.
    activity_semantic_index = get_activity_semantic_index(
        schedule_activities, activity_cache_dir or output_dir / "activity_semantic_cache"
    )
    structured_activity_index = None
    if activity_resolver in {"structured", "hybrid"}:
        structured_activity_index = get_structured_activity_index(
            schedule_activities,
            activity_phase=_activity_phase,
            scope_keys=_scope_keys,
        )
    activities, activity_qualities = resolve_activity_matches(
        rows,
        schedule_activities,
        bm25,
        rules,
        activity_semantic_index,
        resolver_mode=activity_resolver,
        structured_index=structured_activity_index,
    )

    t_activities = time.perf_counter()

    # 3. Render output rows from the resolved matches.
    contexts = [
        MatchContext(rule=r, activity=a, rule_quality=q, activity_quality=aq, rule_generic_verdict=gv)
        for r, a, q, aq, gv in zip(
            rules, activities, rule_qualities, activity_qualities, generic_verdicts, strict=True
        )
    ]
    output_rows = [
        _format_schedule_row(row, ctx, shift_days)
        for row, ctx in zip(rows, contexts, strict=True)
    ]

    t_format = time.perf_counter()

    output_stem = _output_stem(input_csv)
    if ntp_date:
        output_stem = f"{output_stem}_ntp{ntp_date}"
    if activity_resolver != "text":
        output_stem = f"{output_stem}_resolver-{activity_resolver}"
    if limit > 0:
        output_stem = f"{output_stem}_limit{limit}"
    _log(f"Writing generated schedule with stem: {output_stem}")
    xlsx_path, json_path = write_schedule_outputs(output_dir, output_stem, output_rows)

    t_end = time.perf_counter()

    timing: dict[str, Any] = {
        "csv_read_s": round(t_read - t0, 3),
        "loader_setup_s": round(t_load - t_read, 3),
        "rule_resolution_s": round(t_rules - t_load, 3),
        "activity_resolution_s": round(t_activities - t_rules, 3),
        "format_s": round(t_format - t_activities, 3),
        "write_s": round(t_end - t_format, 3),
        "total_s": round(t_end - t0, 3),
        "rows_input": original_count,
        "rows_processed": len(rows),
        "activity_resolver": activity_resolver,
        **candidate_filter,
        "use_semantic_rules": bool(rule_semantic_index),
        "use_semantic_activities": bool(activity_semantic_index),
    }
    logger.info(
        "Timing — read: {csv_read_s}s | loader: {loader_setup_s}s"
        " | rules: {rule_resolution_s}s | activities: {activity_resolution_s}s"
        " | format: {format_s}s | write: {write_s}s | total: {total_s}s",
        **timing,
    )
    return xlsx_path, json_path, timing


def _format_schedule_row(
    row: dict[str, str],
    ctx: MatchContext,
    shift_days: int = 0,
) -> dict[str, Any]:
    """Format one generated schedule row with FA/FC date ranges from a resolved match."""
    title = row.get("Title", "").strip()
    deliverable = row.get("Deliverable", "").strip()
    equipment = row.get("Equipment", "").strip()
    system = row.get("System", "").strip()
    building = row.get("Building", "").strip()

    rule_query = build_rule_query(row)
    rule = ctx.rule
    activity = ctx.activity

    sub_type = rule.sub_type if rule else ""
    rule_name = rule.item_name if rule else ""
    rule_keyword = rule.doc_keyword if rule else ""
    rule_priority = rule.priority if rule else ""
    vt_parsed: dict = rule.vt_parsed if rule else {}
    vt_raw = vt_parsed.get("raw", "") if vt_parsed else ""
    vt_description = rule.describe() if rule and vt_parsed else ""
    rule_quality_fields = ctx.rule_quality.output_fields() if ctx.rule_quality else {}
    activity_quality_fields = ctx.activity_quality.output_fields() if ctx.activity_quality else {}
    generic_judge_fields = ctx.rule_generic_verdict.output_fields() if ctx.rule_generic_verdict else {}

    # Compute FA/FC date ranges only when rule/activity quality passes the generation gate.
    dr = DateRange()
    date_range_status = "no_rule"
    date_range_block_reasons: list[str] = []
    if rule and sub_type == "SKIP":
        date_range_status = "skip"
    elif rule:
        date_range_status, date_range_block_reasons = _date_range_gate(ctx.rule_quality, ctx.activity_quality)
        if date_range_status == "generated":
            anchor = resolve_anchor_date(activity.start_date, activity.finish_date, rule, shift_days)
            ntp_floor = TEMPLATE_NTP + timedelta(days=shift_days) if shift_days else None
            dr = compute_date_range(vt_parsed, anchor, sub_type, rule.priority, ntp_floor=ntp_floor)
            date_range_status = _date_range_status(anchor, dr)
            # Lever D: "For Information" documents have no approval cycle, so the
            # absence of an FA date is correct, not a defect. When an FI rule yields a
            # submission (FC) date but no FA, surface it as a complete FI outcome
            # instead of the misleading "missing_fa". FA docs lacking FA stay missing_fa.
            if sub_type == "FI" and date_range_status == "missing_fa":
                date_range_status = "fi_complete"
    schedule_quality = _schedule_quality(row, ctx, dr, date_range_status, date_range_block_reasons)

    return {
        "source_file": row.get("Source File", ""),
        "document_no": row.get("Document No", "").strip(),
        "title": title,
        "deliverable": deliverable,
        "equipment": equipment,
        "system": system,
        "building": building,
        "itb_sources": row.get("itb_sources", ""),
        "rule_query": rule_query,
        "matched_rule": rule_name,
        "matched_rule_keyword": rule_keyword,
        "matched_rule_priority": rule_priority,
        "matched_rule_validation_time": vt_raw,
        "matched_rule_date_formula": vt_description,
        **rule_quality_fields,
        **generic_judge_fields,
        "submission_type": sub_type,
        "matched_activity_id": activity.activity_id,
        "matched_activity_name": activity.activity_name_clean or activity.activity_name,
        "matched_activity_wbs_path": activity.wbs_path,
        "matched_activity_start_date": activity.start_date,
        "matched_activity_finish_date": activity.finish_date,
        **activity_quality_fields,
        "fa_earliest": _fmt_date(dr.fa_earliest),
        "fa_recommended": _fmt_date(dr.fa_recommended),
        "fa_latest": _fmt_date(dr.fa_latest),
        "fc_earliest": _fmt_date(dr.fc_earliest),
        "fc_recommended": _fmt_date(dr.fc_recommended),
        "fc_latest": _fmt_date(dr.fc_latest),
        "date_range_status": date_range_status,
        "date_range_confidence": f"{dr.confidence:.2f}" if dr.confidence else "",
        "schedule_confidence": _fmt_confidence(schedule_quality["confidence"]),
        "schedule_quality_status": schedule_quality["status"],
        "schedule_quality_reasons": schedule_quality["reasons"],
        "date_range_notes": dr.notes,
        "ntp_shift_days": shift_days if shift_days else "",
    }


def _schedule_quality(
    row: dict[str, str],
    ctx: MatchContext,
    dr: DateRange,
    date_range_status: str,
    date_range_block_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Compute end-to-end schedule confidence from candidate, rule, activity, and date quality."""
    date_range_block_reasons = date_range_block_reasons or []
    if date_range_status == "skip":
        return {"status": "skip", "confidence": 0.0, "reasons": "date_status=skip"}
    if date_range_status == "no_rule":
        reason = "no_rule"
        if ctx.rule_quality and ctx.rule_quality.guard_status == "rejected":
            reason = f"rule_guard_rejected:{ctx.rule_quality.guard_reason}"
        return {"status": "blocked_no_rule", "confidence": 0.0, "reasons": reason}
    if date_range_status in {"blocked_rule", "blocked_activity", "blocked_rule_activity"}:
        return {
            "status": date_range_status,
            "confidence": 0.0,
            "reasons": ";".join(date_range_block_reasons),
        }
    if date_range_status not in {"generated", "fi_complete"}:
        return {"status": "blocked_missing_date", "confidence": 0.0, "reasons": f"date_status={date_range_status}"}

    candidate_component, candidate_reason = _candidate_quality_component(row)
    rule_component, rule_status, rule_reasons = _rule_quality_component(ctx.rule_quality)
    activity_component, activity_status, activity_reasons = _activity_quality_component(ctx.activity_quality)
    date_component, date_reason = _date_quality_component(ctx.rule, dr)

    confidence = candidate_component * rule_component * activity_component * date_component
    caps: list[float] = []
    reasons = [reason for reason in [candidate_reason, date_reason, *rule_reasons, *activity_reasons] if reason]
    reasons = _apply_generic_verdict(reasons, ctx.rule_generic_verdict)

    if rule_status == "needs_review_rule":
        caps.append(0.4)
    if activity_status == "needs_review_activity":
        caps.append(0.5)
    if ctx.activity_quality and ctx.activity_quality.generic_activity:
        caps.append(0.8)
    if date_reason == "default_fc_window":
        caps.append(0.9)
    if caps:
        confidence = min(confidence, min(caps))

    if candidate_reason.startswith("candidate_status="):
        status = "needs_review_candidate"
    elif rule_status == "needs_review_rule":
        status = "needs_review_rule"
    elif activity_status == "needs_review_activity":
        status = "needs_review_activity"
    elif confidence >= 0.55 and not _has_rule_ambiguity_reasons(reasons):
        status = "usable"
    else:
        status = "needs_review"

    # Lever D: keep "for information" completions visible as their own outcome.
    if date_range_status == "fi_complete" and status == "usable":
        status = "fi_complete"

    return {
        "status": status,
        "confidence": confidence,
        "reasons": ";".join(reasons),
    }


def _date_range_gate(
    rule_quality: RuleMatchQuality | None,
    activity_quality: ActivityMatchQuality | None,
) -> tuple[str, list[str]]:
    """Return a gating status for date generation based on rule/activity quality."""
    rule_block_reasons = _rule_block_reasons(rule_quality)
    activity_block_reasons = _activity_block_reasons(activity_quality)
    if rule_block_reasons and activity_block_reasons:
        return "blocked_rule_activity", [*rule_block_reasons, *activity_block_reasons]
    if rule_block_reasons:
        return "blocked_rule", rule_block_reasons
    if activity_block_reasons:
        return "blocked_activity", activity_block_reasons
    return "generated", []


def _rule_block_reasons(quality: RuleMatchQuality | None) -> list[str]:
    """Return reasons that make a rule too unreliable for date generation."""
    if quality is None:
        return []
    reasons = []
    if quality.guard_status == "rejected":
        reasons.append(f"rule_guard_rejected:{quality.guard_reason}")
    if quality.family_status == "mismatch":
        reasons.append("rule_family_mismatch")
    if getattr(quality, "subtype_status", "") == "mismatch":
        reasons.append("rule_subtype_mismatch")
    if quality.scope_status == "mismatch":
        reasons.append("rule_scope_mismatch")
    if quality.final_score < 0.5:
        # Semantic confirmation bypass: short rules (1–2 tokens) and priority-3 generic
        # rules carry a structural score penalty — max(|kw|,3) token normalisation and
        # ×0.70 priority weight — that is unrelated to match correctness.  When family +
        # subtype both confirm the deliverable type AND the embedding similarity is strong
        # (≥0.60), the low final_score is a formula artefact, not evidence of a wrong match.
        _semantically_confirmed = (
            quality.family_status == "match"
            and quality.subtype_status == "match"
            and quality.semantic_score >= 0.60
            and quality.scope_status != "mismatch"
        )
        if not _semantically_confirmed:
            reasons.append("rule_score_below_gate")
            # Scope-ambiguous rules are allowed when score ≥ 0.5; when below the gate
            # and not semantically confirmed, add the ambiguity tag so reviewers know why.
            if quality.scope_status in {"rule_generic", "query_unscoped", "no_rule"}:
                reasons.append(f"rule_scope_ambiguous:{quality.scope_status}")
            if quality.family_status in {
                "compatible", "unknown", "missing_rule_family", "missing_query_family"
            }:
                reasons.append(f"rule_family_uncertain:{quality.family_status}")
    return reasons


def _activity_block_reasons(quality: ActivityMatchQuality | None) -> list[str]:
    """Return reasons that make an activity too unreliable for date generation."""
    if quality is None:
        return []
    reasons = []
    if quality.phase_status == "mismatch":
        reasons.append("activity_phase_mismatch")
    if quality.scope_status == "mismatch":
        reasons.append("activity_scope_mismatch")
    if getattr(quality, "scope_source", "") == "rule" and quality.scope_status != "match":
        # Bypass: when the activity is unscoped (generic CCPP template with no explicit
        # equipment scope) and the semantic + RRF scores confirm a good conceptual match,
        # the scope gap is a data gap in the activity, not evidence of a wrong match.
        # Does NOT bypass real scope mismatches (scope_status="mismatch") or low-confidence
        # matches (semantic<0.55 or rrf<0.01).
        _unscoped_confirmed = (
            quality.scope_status == "activity_unscoped"
            and quality.phase_status in {"match", "compatible"}
            and quality.semantic_score >= 0.55
            and quality.rrf_score >= 0.01
        )
        if not _unscoped_confirmed:
            reasons.append("activity_rule_scope_unmatched")
    # Activity gates: lowered from 0.02/0.015 to 0.01/0.005 so that moderately-matched
    # activities produce a draft date (needs_review) rather than a hard block.  Quality
    # scoring already applies confidence penalties for these cases.
    if quality.rrf_score < 0.01:
        reasons.append("activity_rrf_below_gate")
    if quality.generic_activity and quality.adjusted_score < 0.005:
        reasons.append("activity_generic_low_confidence")
    if (
        quality.query_phase in {"system_design", "design_drawing", "design_criteria", "civil_design"}
        and quality.activity_phase == "procurement"
    ):
        reasons.append("activity_phase_procurement_conflict")
    return reasons


def _apply_generic_verdict(reasons: list[str], verdict: GenericVerdict | None) -> list[str]:
    """Let a rule_generic verdict clear (or annotate) the generic-scope ambiguity.

    Phase 1 is verify-only: a promoting verdict removes the ``rule_scope_status=rule_generic``
    ambiguity tag so the row can become ``usable`` — it never changes the computed dates.
    Every verdict is also recorded as a ``rule_generic_judge=...`` reason for audit.
    """
    if verdict is None:
        return reasons
    out = list(reasons)
    if verdict.promotes:
        out = [r for r in out if r != "rule_scope_status=rule_generic"]
        out.append(f"rule_generic_judge={verdict.bucket}:{verdict.verdict or 'safe'}")
    elif verdict.flags_wrong:
        out.append("rule_generic_judge=use_specific")
    else:
        out.append("rule_generic_judge=uncertain")
    return out


def _has_rule_ambiguity_reasons(reasons: list[str]) -> bool:
    """Keep rows with ambiguous rule identity in review even when other signals are strong."""
    ambiguous = {
        "rule_family_status=compatible",
        "rule_family_status=unknown",
        "rule_family_status=missing_rule_family",
        "rule_family_status=missing_query_family",
        "rule_scope_status=query_unscoped",
        "rule_scope_status=rule_generic",
    }
    return any(reason in ambiguous for reason in reasons)


def _candidate_quality_component(row: dict[str, str]) -> tuple[float, str]:
    status = row.get("candidate_status", "").strip().lower()
    if status and status != "accepted":
        return 0.4, f"candidate_status={status}"
    raw_score = row.get("match_score", "").strip()
    if not raw_score:
        # No match_score column → row comes from a historical MDL file, not from the
        # ITB candidate pipeline.  There is no candidate-quality signal to penalise.
        return 1.0, ""
    try:
        score = float(raw_score)
    except ValueError:
        return 0.75, "candidate_score_missing"
    if score >= 0.82:
        return 1.0, ""
    if score >= 0.78:
        return 0.85, "candidate_score_medium"
    if score >= 0.75:
        return 0.7, "candidate_score_low"
    return 0.5, "candidate_score_below_threshold"


def _rule_quality_component(quality: RuleMatchQuality | None) -> tuple[float, str, list[str]]:
    if quality is None:
        return 0.5, "needs_review_rule", ["rule_quality_missing"]
    reasons = []
    if quality.guard_status == "rejected":
        return 0.1, "needs_review_rule", [f"rule_guard_rejected:{quality.guard_reason}"]
    component = 1.0
    status = "usable"
    if quality.family_status == "mismatch":
        component *= 0.3
        status = "needs_review_rule"
        reasons.append("rule_family_mismatch")
    elif quality.family_status in {"compatible", "missing_rule_family", "missing_query_family", "unknown"}:
        component *= 0.75
        reasons.append(f"rule_family_status={quality.family_status}")
    subtype_status = getattr(quality, "subtype_status", "")
    if subtype_status == "mismatch":
        component *= 0.3
        status = "needs_review_rule"
        reasons.append("rule_subtype_mismatch")
    elif subtype_status in {"compatible", "unknown"}:
        component *= 0.9
        reasons.append(f"rule_subtype_status={subtype_status}")
    if quality.scope_status == "mismatch":
        component *= 0.3
        status = "needs_review_rule"
        reasons.append("rule_scope_mismatch")
    elif quality.scope_status in {"rule_generic", "query_unscoped", "no_rule"}:
        component *= 0.8
        reasons.append(f"rule_scope_status={quality.scope_status}")
    if quality.final_score < 0.3:
        component *= 0.7
        reasons.append("rule_score_low")
    elif quality.final_score < 0.5:
        component *= 0.85
        reasons.append("rule_score_medium")
    return component, status, reasons


def _activity_quality_component(quality: ActivityMatchQuality | None) -> tuple[float, str, list[str]]:
    if quality is None:
        return 0.5, "needs_review_activity", ["activity_quality_missing"]
    reasons = []
    component = 1.0
    status = "usable"
    if quality.phase_status == "mismatch":
        component *= 0.3
        status = "needs_review_activity"
        reasons.append("activity_phase_mismatch")
    elif quality.phase_status in {"compatible", "query_unknown", "activity_unknown"}:
        component *= 0.75
        reasons.append(f"activity_phase_status={quality.phase_status}")
    if quality.scope_status == "mismatch":
        component *= 0.3
        status = "needs_review_activity"
        reasons.append("activity_scope_mismatch")
    elif quality.scope_status == "discipline_only":
        # Overlaps only on a cross-cutting discipline (electrical/HVAC); the document's
        # equipment system is unconfirmed, so the anchor is likely the wrong system.
        component *= 0.5
        reasons.append("activity_scope_status=discipline_only")
    elif quality.scope_status in {"activity_unscoped", "query_unscoped"}:
        component *= 0.8
        reasons.append(f"activity_scope_status={quality.scope_status}")
    if getattr(quality, "scope_source", "") == "rule":
        if quality.scope_status != "match":
            component *= 0.5
            status = "needs_review_activity"
            reasons.append("activity_rule_scope_unmatched")
        else:
            reasons.append("activity_scope_source=rule")
    if quality.generic_activity:
        component *= 0.8
        reasons.append("activity_generic")
    if quality.rrf_score < 0.02:
        component *= 0.85
        reasons.append("activity_rrf_low")
    return component, status, reasons


def _date_quality_component(rule: ValidationRule | None, dr: DateRange) -> tuple[float, str]:
    if rule is None:
        return 0.0, "no_rule"
    vt_parsed = rule.vt_parsed or {}
    if dr.fa_recommended and dr.fc_recommended and not vt_parsed.get("has_fc_rule"):
        return 0.9, "default_fc_window"
    return 1.0, ""


def _date_range_status(anchor: date | None, dr: DateRange) -> str:
    """Return an output status that reflects date completeness, not only rule match success."""
    if anchor is None:
        return "missing_date"
    if not dr.fa_recommended and not dr.fc_recommended:
        return "missing_date_range"
    if not dr.fa_recommended:
        return "missing_fa"
    if not dr.fc_recommended:
        return "missing_fc"
    return "generated"


def _compute_shift(ntp_date: str) -> int:
    """Return days to shift guide schedule dates given a real project NTP date."""
    if not ntp_date:
        return 0
    try:
        return (date.fromisoformat(ntp_date) - TEMPLATE_NTP).days
    except ValueError:
        logger.warning("Invalid ntp_date '{}' — using template dates", ntp_date)
        return 0


def _fmt_date(d: date | None) -> str:
    return d.isoformat() if d is not None else ""


def _fmt_confidence(value: float) -> str:
    return f"{max(0.0, min(value, 1.0)):.2f}"


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read an MDL classified CSV file."""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _filter_schedulable_candidates(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """For schedule candidate CSVs, keep review candidates in the generated output.

    Historical *_MDL_classified.csv inputs do not have candidate_status and keep the
    previous behavior. Candidate CSVs from /schedule/candidates include the column.
    Accepted and needs_review rows are both useful: accepted rows may be auto-scored,
    while needs_review rows are generated with schedule_quality_status=needs_review_candidate.
    """
    if not rows or "candidate_status" not in rows[0]:
        return rows, {
            "candidate_filter_applied": False,
            "rows_skipped_non_accepted": 0,
            "rows_included_non_accepted": 0,
            "candidate_selection_filter_applied": False,
            "rows_skipped_not_selected": 0,
        }
    selection_filter_applied = "candidate_selection_status" in rows[0]
    if selection_filter_applied:
        before_selection = len(rows)
        rows = [
            row for row in rows if row.get("candidate_selection_status", "").strip().lower() == "selected"
        ]
        skipped_not_selected = before_selection - len(rows)
        if skipped_not_selected:
            _log(f"Candidate selection filter enabled: skipping {skipped_not_selected} backup rows")
    else:
        skipped_not_selected = 0
    schedulable_statuses = {"accepted", "needs_review"}
    schedulable = [
        row for row in rows if row.get("candidate_status", "").strip().lower() in schedulable_statuses
    ]
    included_non_accepted = sum(
        row.get("candidate_status", "").strip().lower() != "accepted" for row in schedulable
    )
    skipped = len(rows) - len(schedulable)
    if included_non_accepted:
        _log(f"Candidate review path enabled: including {included_non_accepted} non-accepted rows")
    if skipped:
        _log(f"Candidate filter enabled: skipping {skipped} rows with unsupported candidate_status")
    return schedulable, {
        "candidate_filter_applied": True,
        "rows_skipped_non_accepted": skipped,
        "rows_included_non_accepted": included_non_accepted,
        "candidate_selection_filter_applied": selection_filter_applied,
        "rows_skipped_not_selected": skipped_not_selected,
    }


def _output_stem(input_csv: Path) -> str:
    """Build the generated schedule output stem."""
    return f"generated_schedule_{input_csv.stem}"


def main() -> None:
    """Run the schedule generator CLI."""
    parser = argparse.ArgumentParser(description="Generate FA/FC date ranges from MDL classified CSV files.")
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N rows from each input CSV.")
    parser.add_argument(
        "--activity-resolver",
        choices=("text", "structured", "hybrid"),
        default="text",
        help="Activity resolution mode: legacy text retrieval, structured system-phase lookup, or hybrid fallback.",
    )
    parser.add_argument(
        "--ntp-date",
        default="",
        help="Real project NTP date in ISO format (e.g. 2024-01-15). Shifts all guide schedule dates accordingly.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="One or more *_MDL_classified.csv files.")
    args = parser.parse_args()

    _log(f"Loading schedule activities: {args.schedule}")
    activities = load_schedule_activities(args.schedule)
    _log(f"Loaded {len(activities)} schedule activities")
    for input_csv in args.inputs:
        xlsx_path, json_path, _timing = generate_schedule_file(
            input_csv=input_csv,
            schedule_activities=activities,
            output_dir=args.output_dir,
            limit=args.limit,
            ntp_date=args.ntp_date,
            semantic_cache_dir=args.output_dir / "rule_semantic_cache",
            activity_cache_dir=args.output_dir / "activity_semantic_cache",
            activity_resolver=args.activity_resolver,
        )
        logger.info("Wrote generated schedule workbook: {}", xlsx_path)
        logger.info("Wrote generated schedule JSON: {}", json_path)


def _log(message: str) -> None:
    """Log a schedule generator message."""
    logger.info(message)


if __name__ == "__main__":
    main()
