#!/usr/bin/env python3
"""
Read-only feasibility probe: structured (system x phase) activity anchoring.
===========================================================================

Question: of the activity-blocked rows (no date), how many would anchor if we
looked the schedule up by (system, engineering-phase) instead of fuzzy text?

It does NOT change the matcher. It reuses the matcher's OWN classifiers
(_activity_phase, _scope_keys, _PHASE_BUCKETS) to:
  1. index the 4039 guide-schedule activities into (system, phase) cells,
  2. for each blocked row, read its already-computed (effective_scope, query_phase),
  3. bucket each row: recoverable / phase-gap / system-absent / no-system / no-phase.

Usage:
  PYTHONPATH=src python scripts/probe_structured_activity_coverage.py \
    output/schedule_service/generate/generated_schedule_Fadhili_MDL_classified_ntp2024-03-01.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

from schedule_service.generate.activity.loader import DEFAULT_SCHEDULE_PATH, load_schedule_activities
from schedule_service.generate.activity.matcher import _PHASE_BUCKETS, _activity_phase, _scope_keys


def build_schedule_index():
    """Return (cells, systems, cell_examples) keyed by (system, activity_phase)."""
    activities = load_schedule_activities(DEFAULT_SCHEDULE_PATH)
    cells: set[tuple[str, str]] = set()
    systems: set[str] = set()
    examples: dict[tuple[str, str], str] = {}
    for a in activities:
        text = " ".join([a.activity_name_clean or "", a.activity_name or "", a.wbs_path or ""])
        phase = _activity_phase(text)
        sys_keys = _scope_keys(text)
        for s in sys_keys:
            systems.add(s)
            if phase:
                cells.add((s, phase))
                examples.setdefault((s, phase), f"{a.activity_name_clean}  [{a.start_date}..{a.finish_date}]")
    return cells, systems, examples, len(activities)


def allowed_phases(query_phase: str) -> set[str]:
    """Activity phases that satisfy a query phase, per the matcher's own buckets."""
    bucket = set(_PHASE_BUCKETS.get(query_phase, ()))
    return bucket or ({query_phase} if query_phase else set())


def main() -> None:
    out_json = sys.argv[1]
    rows = json.load(open(out_json, encoding="utf-8"))
    g = lambda r, k: str(r.get(k) or "").strip()

    cells, systems, examples, n_act = build_schedule_index()
    print(f"Schedule: {n_act} activities -> {len(systems)} systems, {len(cells)} distinct (system,phase) cells\n")

    blocked = [r for r in rows if g(r, "date_range_status") in ("blocked_activity", "blocked_rule_activity")]
    print(f"Activity-blocked rows: {len(blocked)}\n")

    buckets: Counter = Counter()
    recoverable_samples = []
    gap_samples = []
    for r in blocked:
        scope_field = g(r, "activity_match_effective_scope") or g(r, "activity_match_query_scope")
        sys_keys = [s for s in scope_field.split("|") if s]
        qphase = g(r, "activity_match_query_phase")

        if not sys_keys:
            buckets["A_no_system (no scope -> cannot anchor)"] += 1
            continue
        if not qphase:
            buckets["D_no_phase (deliverable->phase unresolved)"] += 1
            continue

        aphases = allowed_phases(qphase)
        hit = next((((s, p)) for s in sys_keys for p in aphases if (s, p) in cells), None)
        if hit:
            buckets["B_recoverable (system,phase cell EXISTS)"] += 1
            if len(recoverable_samples) < 12:
                recoverable_samples.append((g(r, "title"), sys_keys, qphase, examples[hit]))
        elif any(s in systems for s in sys_keys):
            buckets["C_phase_gap (system in schedule, phase milestone missing)"] += 1
            if len(gap_samples) < 10:
                gap_samples.append((g(r, "title"), sys_keys, qphase))
        else:
            buckets["E_system_absent (system not in guide schedule)"] += 1

    total = len(blocked)
    print("=== Coverage of activity-blocked rows under structured (system x phase) lookup ===")
    for k in [
        "B_recoverable (system,phase cell EXISTS)",
        "C_phase_gap (system in schedule, phase milestone missing)",
        "E_system_absent (system not in guide schedule)",
        "A_no_system (no scope -> cannot anchor)",
        "D_no_phase (deliverable->phase unresolved)",
    ]:
        c = buckets.get(k, 0)
        print(f"  {c:5} ({c/total*100:4.1f}%)  {k}")

    print("\n--- B_recoverable samples (doc | system | qphase -> existing milestone) ---")
    for t, s, q, ex in recoverable_samples:
        print(f"  '{t[:36]}' | {s} | {q} -> {ex[:54]}")
    print("\n--- C_phase_gap samples (system exists, no such phase milestone) ---")
    for t, s, q in gap_samples:
        print(f"  '{t[:40]}' | {s} | needs phase '{q}'")


if __name__ == "__main__":
    main()
