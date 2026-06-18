"""Calibrate the deliverable-concept promotion threshold (tau) from a generated schedule.

Run AFTER a /generate run with the deliverable_concept_sim signal enabled. Reads the new
`rule_match_deliverable_concept_sim` field straight from the output JSON (no Azure needed),
restricts to the "all-green sub-0.55" promotion-candidate set, and prints the similarity
distribution so tau can be placed in the gap between true matches and wrong-discipline
generic matches.

    python scripts/calibrate_deliverable_concept_sim.py <generated_schedule.json>
"""

from __future__ import annotations

import json
import sys
from collections import Counter


def _is(x: str) -> bool:
    return str(x).strip().lower() in ("true", "1", "yes")


def _rule_confirmed(r: dict) -> bool:
    return (
        r["rule_match_scope_status"] == "match"
        or r.get("rule_generic_judge_bucket") == "g_safe"
        or r.get("rule_generic_judge_verdict") == "generic_ok"
    )


def _candidates(rows: list[dict]) -> list[dict]:
    """All-green rows held below 0.55 — the population the promotion gate targets."""
    out = []
    for r in rows:
        if r["schedule_quality_status"] not in ("needs_review", "needs_review_activity"):
            continue
        if not _rule_confirmed(r):
            continue
        if r["activity_match_scope_status"] != "match":
            continue
        if r["activity_match_phase_status"] not in ("match", "compatible"):
            continue
        if r["date_range_status"] != "generated":
            continue
        if "ntp_anchored_untrusted" in str(r.get("schedule_quality_reasons", "")):
            continue
        if not r.get("rule_match_deliverable_concept_sim"):
            continue
        out.append(r)
    return out


def _suggest_tau(sims: list[float]) -> float:
    """Largest empty gap between 0.40 and 0.90 -> midpoint is the most stable threshold."""
    pts = sorted(s for s in sims if 0.40 <= s <= 0.90)
    if len(pts) < 2:
        return 0.70
    best_gap, best_mid = 0.0, 0.70
    for a, b in zip(pts, pts[1:], strict=True):
        if b - a > best_gap:
            best_gap, best_mid = b - a, (a + b) / 2
    return round(best_mid, 3)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1]) as fh:
        rows = json.load(fh)
    cand = _candidates(rows)
    sims = [float(r["rule_match_deliverable_concept_sim"]) for r in cand]
    print(f"promotion candidates (all-green, sub-0.55): {len(cand)}")
    if not sims:
        print("no deliverable_concept_sim values found — re-run /generate with the new code.")
        return

    print("\nsimilarity histogram (0.05 bins):")
    binned = Counter(round(s // 0.05 * 0.05, 2) for s in sims)
    for lo in [round(0.05 * i, 2) for i in range(0, 20)]:
        n = binned.get(lo, 0)
        if n:
            print(f"  [{lo:.2f},{lo + 0.05:.2f}) {'#' * n} {n}")

    tau = _suggest_tau(sims)
    print(f"\nsuggested tau (widest gap midpoint): {tau}")
    print(f"  would PROMOTE (sim >= {tau}): {sum(1 for s in sims if s >= tau)}")
    print(f"  would HOLD    (sim <  {tau}): {sum(1 for s in sims if s < tau)}")

    cand.sort(key=lambda r: float(r["rule_match_deliverable_concept_sim"]))
    print("\nLOW band (<0.60) — expect wrong-discipline matches:")
    for r in [x for x in cand if float(x["rule_match_deliverable_concept_sim"]) < 0.60][:12]:
        s = r["rule_match_deliverable_concept_sim"]
        print(f"  {s}  '{r['deliverable'][:20]}' -> '{r['matched_rule_keyword'][:30]}' | {r['title'][:34]}")
    print("\nHIGH band (>=0.75) — expect true matches:")
    for r in [x for x in cand if float(x["rule_match_deliverable_concept_sim"]) >= 0.75][:12]:
        s = r["rule_match_deliverable_concept_sim"]
        print(f"  {s}  '{r['deliverable'][:20]}' -> '{r['matched_rule_keyword'][:30]}' | {r['title'][:34]}")


if __name__ == "__main__":
    main()
