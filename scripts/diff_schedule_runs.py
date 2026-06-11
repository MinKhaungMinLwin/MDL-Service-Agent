#!/usr/bin/env python3
"""
Diff two schedule-generate JSON runs (baseline vs candidate).
============================================================

Purpose:
    Measure the effect of a matcher change WITHOUT being fooled by gate-inflation.
    Reports (1) aggregate status deltas and (2) the exact rows whose rule/activity/
    date outcome changed, so a human can judge "real recall gain" vs "noise".

    Critically it flags REGRESSIONS (generated -> blocked, or a match that changed
    on a row that was already usable), which a pure "generated count" would hide.

Alignment:
    Both runs are produced from the same input CSV in the same order, so rows are
    aligned by list index. A title/document_no sanity check guards against drift.

Usage:
    python scripts/diff_schedule_runs.py BASELINE.json CANDIDATE.json \
        --out-dir output/schedule_service/diff
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a JSON list")
    return data


def g(row: dict, key: str) -> str:
    return str(row.get(key) or "").strip()


def status_counts(rows: list[dict], key: str) -> Counter:
    return Counter(g(r, key) for r in rows)


def fmt_delta(name: str, base: Counter, cand: Counter) -> list[str]:
    keys = sorted(set(base) | set(cand), key=lambda k: -(base.get(k, 0) + cand.get(k, 0)))
    lines = [f"\n## {name}", f"{'value':28} {'base':>6} {'cand':>6} {'delta':>7}"]
    for k in keys:
        b, c = base.get(k, 0), cand.get(k, 0)
        arrow = "" if c == b else ("  <== +" if c > b else "  <== ")
        lines.append(f"{k or 'EMPTY':28} {b:>6} {c:>6} {c - b:>+7}{arrow}")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("output/schedule_service/diff"))
    ap.add_argument("--key", default="document_no", help="field for sanity-check alignment")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    base = load(args.baseline)
    cand = load(args.candidate)
    if len(base) != len(cand):
        print(f"WARNING: row count differs base={len(base)} cand={len(cand)}; aligning by min length")
    n = min(len(base), len(cand))

    report: list[str] = [
        "# Schedule run diff",
        f"baseline: {args.baseline}",
        f"candidate: {args.candidate}",
        f"rows compared: {n}",
    ]

    for key in ("date_range_status", "rule_match_scope_status", "activity_match_scope_status",
                "schedule_quality_status", "submission_type"):
        report += fmt_delta(key, status_counts(base[:n], key),
                            status_counts(cand[:n], key))

    # --- per-row transitions on the headline metric ---
    usable = "generated"
    gained, lost, rule_changed, act_changed = [], [], [], []
    title_drift = 0
    for i in range(n):
        b, c = base[i], cand[i]
        if g(b, args.key) and g(b, args.key) != g(c, args.key):
            title_drift += 1
        bs, cs = g(b, "date_range_status"), g(c, "date_range_status")
        if bs != usable and cs == usable:
            gained.append((i, b, c))
        if bs == usable and cs != usable:
            lost.append((i, b, c))
        if g(b, "matched_rule_keyword") != g(c, "matched_rule_keyword"):
            rule_changed.append((i, b, c))
        if g(b, "matched_activity_name") != g(c, "matched_activity_name"):
            act_changed.append((i, b, c))

    if title_drift:
        report.append(f"\n!! ALIGNMENT WARNING: {title_drift} rows differ on '{args.key}' — order may have drifted")

    report += [
        "\n## Headline transitions (date_range_status)",
        f"  gained usable  (blocked->generated): {len(gained)}",
        f"  LOST usable    (generated->blocked): {len(lost)}   <-- regressions, must be ~0",
        f"  rule match changed:                  {len(rule_changed)}",
        f"  activity match changed:              {len(act_changed)}",
    ]

    # --- export changed-row review CSVs ---
    import csv

    def dump(name: str, rows: list[tuple[int, dict, dict]], extra_cols: list[str]) -> None:
        path = args.out_dir / name
        cols = ["idx", "title", "deliverable", "equipment", "system",
                "base_date_status", "cand_date_status"] + extra_cols
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(cols + ["VERDICT(better/worse/same)"])
            for i, b, c in rows:
                base_extra, cand_extra = [], []
                for col in extra_cols:
                    if col.startswith("base_"):
                        base_extra.append(g(b, col[5:]))
                    elif col.startswith("cand_"):
                        cand_extra.append(g(c, col[5:]))
                w.writerow([
                    i, g(c, "title"), g(c, "deliverable"), g(c, "equipment"), g(c, "system"),
                    g(b, "date_range_status"), g(c, "date_range_status"),
                    *base_extra, *cand_extra, "",
                ])
        print(f"wrote {path} ({len(rows)} rows)")

    rule_cols = ["base_matched_rule_keyword", "cand_matched_rule_keyword",
                 "base_submission_type", "cand_submission_type",
                 "base_rule_match_final_score", "cand_rule_match_final_score",
                 "base_fa_recommended", "cand_fa_recommended",
                 "base_fc_recommended", "cand_fc_recommended"]
    dump("changed_rule_match.csv", rule_changed, rule_cols)
    dump("regressions_lost_usable.csv", lost, rule_cols)
    dump("gained_usable.csv", gained, rule_cols)

    text = "\n".join(report)
    (args.out_dir / "diff_report.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nReport: {args.out_dir / 'diff_report.md'}")


if __name__ == "__main__":
    main()
