"""
Compare activity match scores: text resolver (global RRF) vs hybrid structured path (local cell RRF).

Usage:
  PYTHONPATH=src python scripts/plot_resolver_score_comparison.py \
    output/schedule_service/generate/generated_schedule_Fadhili_MDL_classified_ntp2024-03-01.json \
    output/schedule_service/generate/generated_schedule_Fadhili_MDL_classified_ntp2024-03-01_resolver-hybrid.json \
    --out output/schedule_service/resolver_score_comparison.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def flt(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text_json")
    ap.add_argument("hybrid_json")
    ap.add_argument("--out", default="output/schedule_service/resolver_score_comparison.png")
    args = ap.parse_args()

    text_rows = {i: r for i, r in enumerate(load(args.text_json))}
    hybrid_rows = {i: r for i, r in enumerate(load(args.hybrid_json))}

    # ── Collect per-row data ─────────────────────────────────────────────────
    t_rrf, t_adj, t_bm25, t_sem = [], [], [], []
    h_rrf, h_adj, h_bm25, h_sem = [], [], [], []
    outcomes = []          # "gained" / "lost" / "same_usable" / "same_blocked"
    reasons  = []

    usable = {"generated", "fi_complete"}

    for i in text_rows:
        if i not in hybrid_rows:
            continue
        tr = text_rows[i]
        hr = hybrid_rows[i]

        t_rrf.append(flt(tr.get("activity_match_rrf_score")))
        t_adj.append(flt(tr.get("activity_match_adjusted_score")))
        t_bm25.append(flt(tr.get("activity_match_bm25_score")))
        t_sem.append(flt(tr.get("activity_match_semantic_score")))

        h_rrf.append(flt(hr.get("activity_match_rrf_score")))
        h_adj.append(flt(hr.get("activity_match_adjusted_score")))
        h_bm25.append(flt(hr.get("activity_match_bm25_score")))
        h_sem.append(flt(hr.get("activity_match_semantic_score")))

        t_st = tr.get("date_range_status", "")
        h_st = hr.get("date_range_status", "")
        if t_st not in usable and h_st in usable:
            outcomes.append("gained")
        elif t_st in usable and h_st not in usable:
            outcomes.append("lost")
        elif t_st in usable:
            outcomes.append("same_usable")
        else:
            outcomes.append("same_blocked")

        reasons.append(hr.get("activity_match_resolution_reason", ""))

    t_rrf = np.array(t_rrf)
    h_rrf = np.array(h_rrf)
    t_adj = np.array(t_adj)
    h_adj = np.array(h_adj)
    t_bm25 = np.array(t_bm25)
    h_bm25 = np.array(h_bm25)
    t_sem  = np.array(t_sem)
    h_sem  = np.array(h_sem)
    outcomes = np.array(outcomes)
    reasons  = np.array(reasons)

    # ── Colour map ────────────────────────────────────────────────────────────
    color_map = {
        "gained":        "#2ecc71",   # green
        "lost":          "#e74c3c",   # red
        "same_usable":   "#3498db",   # blue
        "same_blocked":  "#bdc3c7",   # grey
    }
    colors = np.array([color_map[o] for o in outcomes])

    # ── Figure layout: 2 rows × 3 cols ────────────────────────────────────────
    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    fig.suptitle(
        "Activity resolver score comparison\nText (global RRF) vs Hybrid structured (local cell RRF)",
        fontsize=14, fontweight="bold", y=0.98,
    )

    # ── Panel 1: RRF scatter — text vs hybrid (all rows) ─────────────────────
    ax = axes[0, 0]
    for outcome, clr, label in [
        ("same_blocked", "#cccccc", "same blocked"),
        ("same_usable",  "#3498db", "same usable"),
        ("gained",       "#2ecc71", "gained usable"),
        ("lost",         "#e74c3c", "lost usable"),
    ]:
        mask = outcomes == outcome
        ax.scatter(t_rrf[mask], h_rrf[mask], c=clr, s=6, alpha=0.55, label=f"{label} (n={mask.sum()})")
    lim = max(t_rrf.max(), h_rrf.max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=0.8, label="y = x")
    ax.axhline(0.02, color="orange", lw=0.8, ls=":", label="rrf gate 0.02")
    ax.axvline(0.02, color="orange", lw=0.8, ls=":")
    ax.set_xlabel("Text RRF score (global rank)")
    ax.set_ylabel("Hybrid RRF score (local cell rank)")
    ax.set_title("RRF score: text vs hybrid (all rows)")
    ax.legend(fontsize=7, markerscale=2)

    # ── Panel 2: Adjusted score scatter ───────────────────────────────────────
    ax = axes[0, 1]
    for outcome, clr, label in [
        ("same_blocked", "#cccccc", "same blocked"),
        ("same_usable",  "#3498db", "same usable"),
        ("gained",       "#2ecc71", "gained"),
        ("lost",         "#e74c3c", "lost"),
    ]:
        mask = outcomes == outcome
        ax.scatter(t_adj[mask], h_adj[mask], c=clr, s=6, alpha=0.55, label=f"{label} (n={mask.sum()})")
    lim = max(t_adj.max(), h_adj.max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=0.8)
    ax.set_xlabel("Text adjusted score")
    ax.set_ylabel("Hybrid adjusted score")
    ax.set_title("Adjusted score: text vs hybrid")
    ax.legend(fontsize=7, markerscale=2)

    # ── Panel 3: Semantic score scatter (BM25 independent signal) ────────────
    ax = axes[0, 2]
    for outcome, clr, label in [
        ("same_blocked", "#cccccc", "same blocked"),
        ("same_usable",  "#3498db", "same usable"),
        ("gained",       "#2ecc71", "gained"),
        ("lost",         "#e74c3c", "lost"),
    ]:
        mask = outcomes == outcome
        ax.scatter(t_sem[mask], h_sem[mask], c=clr, s=6, alpha=0.55, label=f"{label} (n={mask.sum()})")
    lim = max(t_sem.max(), h_sem.max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=0.8)
    ax.set_xlabel("Text semantic score (activity selected by text)")
    ax.set_ylabel("Hybrid semantic score (activity selected by hybrid)")
    ax.set_title("Semantic score of selected activity")
    ax.legend(fontsize=7, markerscale=2)

    # ── Panel 4: RRF improvement delta histogram ──────────────────────────────
    ax = axes[1, 0]
    delta_rrf = h_rrf - t_rrf
    gained_mask  = outcomes == "gained"
    lost_mask    = outcomes == "lost"
    other_mask   = ~(gained_mask | lost_mask)
    bins = np.linspace(delta_rrf.min(), delta_rrf.max(), 60)
    ax.hist(delta_rrf[other_mask],  bins=bins, color="#bdc3c7", alpha=0.7, label="no outcome change")
    ax.hist(delta_rrf[gained_mask], bins=bins, color="#2ecc71", alpha=0.9, label=f"gained ({gained_mask.sum()})")
    ax.hist(delta_rrf[lost_mask],   bins=bins, color="#e74c3c", alpha=0.9, label=f"lost ({lost_mask.sum()})")
    ax.axvline(0, color="black", lw=1)
    ax.set_xlabel("Δ RRF score (hybrid − text)")
    ax.set_ylabel("Row count")
    ax.set_title("RRF delta distribution\n(+ve = hybrid scored higher)")
    ax.legend(fontsize=8)

    # ── Panel 5: RRF distribution by resolution reason ───────────────────────
    ax = axes[1, 1]
    reason_colors = {
        "structured_preferred":             "#2ecc71",
        "structured_cell_found_text_preferred": "#f39c12",
        "structured_no_system":             "#95a5a6",
        "structured_no_phase":              "#bdc3c7",
        "structured_phase_gap":             "#7f8c8d",
        "structured_system_absent":         "#c0392b",
    }
    reason_order = [
        "structured_preferred",
        "structured_cell_found_text_preferred",
        "structured_no_system",
        "structured_no_phase",
        "structured_phase_gap",
        "structured_system_absent",
    ]
    for reason in reason_order:
        mask = reasons == reason
        if mask.sum() == 0:
            continue
        ax.hist(
            h_rrf[mask], bins=50, alpha=0.65,
            color=reason_colors.get(reason, "gray"),
            label=f"{reason} (n={mask.sum()})",
            density=True,
        )
    ax.axvline(0.02, color="orange", lw=1, ls="--", label="rrf gate 0.02")
    ax.set_xlabel("Hybrid RRF score")
    ax.set_ylabel("Density")
    ax.set_title("RRF distribution by resolution reason")
    ax.legend(fontsize=6)

    # ── Panel 6: outcome breakdown by resolution reason ───────────────────────
    ax = axes[1, 2]
    reason_labels = [r for r in reason_order if (reasons == r).sum() > 0]
    outcome_labels = ["gained", "same_usable", "same_blocked", "lost"]
    outcome_colors = ["#2ecc71", "#3498db", "#bdc3c7", "#e74c3c"]
    x = np.arange(len(reason_labels))
    width = 0.18
    for j, (out, clr) in enumerate(zip(outcome_labels, outcome_colors)):
        counts = [(outcomes[(reasons == r)]).tolist().count(out) for r in reason_labels]
        ax.bar(x + j * width, counts, width, label=out, color=clr, alpha=0.85)
    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels(
        [r.replace("structured_", "").replace("_", "\n") for r in reason_labels],
        fontsize=7,
    )
    ax.set_ylabel("Row count")
    ax.set_title("Outcome by resolution reason")
    ax.legend(fontsize=7)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")

    # ── Summary stats ─────────────────────────────────────────────────────────
    print("\n=== Score summary by resolution path ===")
    for reason in reason_order:
        mask = reasons == reason
        if mask.sum() == 0:
            continue
        print(f"\n{reason} (n={mask.sum()})")
        print(f"  text  rrf: mean={t_rrf[mask].mean():.4f}  median={np.median(t_rrf[mask]):.4f}  >0.02: {(t_rrf[mask]>0.02).sum()}")
        print(f"  hybr  rrf: mean={h_rrf[mask].mean():.4f}  median={np.median(h_rrf[mask]):.4f}  >0.02: {(h_rrf[mask]>0.02).sum()}")
        print(f"  hybr  sem: mean={h_sem[mask].mean():.4f}  t_sem mean={t_sem[mask].mean():.4f}")
        gained_n = ((outcomes == "gained") & mask).sum()
        lost_n   = ((outcomes == "lost")   & mask).sum()
        print(f"  gained={gained_n}  lost={lost_n}")


if __name__ == "__main__":
    main()
