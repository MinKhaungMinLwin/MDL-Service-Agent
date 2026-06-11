#!/usr/bin/env python3
"""
Visualize activity-match score gaps across resolver modes.

Purpose:
    Compare the final selected activity-match scores from the existing schedule
    benchmark outputs:
      - text       : full search against the 4039 activity catalog
      - structured : cell-constrained lookup using system/phase when available
      - hybrid     : structured-first with text fallback

    The benchmark CSVs do not store all 4039 candidate scores per row, only the
    selected activity's score fields. This script therefore visualizes score gaps
    on the final chosen activity per document row.

Outputs:
    - score_gap_summary.csv
    - score_gap_report.md
    - activity_score_delta_hist.png
    - activity_score_delta_ecdf.png
    - activity_score_absolute_box.png
    - activity_score_reason_box_hybrid.png
    - activity_score_top_deltas_structured.png
    - activity_score_top_deltas_hybrid.png
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

import pandas as pd


PRIMARY_SCORE = "activity_match_adjusted_score"
MODE_LABELS = {
    "text": "Text (4039 search)",
    "structured": "Structured (cell-constrained)",
    "hybrid": "Hybrid",
}
SCORE_FIELDS = [
    "activity_match_bm25_score",
    "activity_match_semantic_score",
    "activity_match_rrf_score",
    "activity_match_adjusted_score",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--text-csv",
        type=Path,
        default=Path("output/schedule_service/bench_text/normalized_output.csv"),
    )
    parser.add_argument(
        "--structured-csv",
        type=Path,
        default=Path("output/schedule_service/bench_structured/normalized_output.csv"),
    )
    parser.add_argument(
        "--hybrid-csv",
        type=Path,
        default=Path("output/schedule_service/bench_hybrid/normalized_output.csv"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("output/schedule_service/activity_score_gap"),
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=30,
        help="Rows per mode to show in the top delta dumbbell chart.",
    )
    return parser.parse_args()


def get_plt():
    import matplotlib.pyplot as plt

    return plt


def load_mode(path: Path, mode: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df.reset_index(names="row_idx")
    rename = {
        "matched_activity_name": f"{mode}_activity_name",
        "activity_match_resolution_reason": f"{mode}_resolution_reason",
        "activity_match_resolver_mode": f"{mode}_resolver_mode",
        "date_range_status": f"{mode}_date_range_status",
        "schedule_quality_status": f"{mode}_schedule_quality_status",
    }
    for field in SCORE_FIELDS:
        rename[field] = f"{mode}_{field}"
    keep = [
        "row_idx",
        "source_file",
        "document_no",
        "title",
        "deliverable",
        "equipment",
        "system",
        "matched_activity_name",
        "activity_match_resolution_reason",
        "activity_match_resolver_mode",
        "date_range_status",
        "schedule_quality_status",
        *SCORE_FIELDS,
    ]
    return df[keep].rename(columns=rename)


def build_comparison(text_df: pd.DataFrame, structured_df: pd.DataFrame, hybrid_df: pd.DataFrame) -> pd.DataFrame:
    merged = text_df.merge(
        structured_df,
        on=["row_idx", "source_file", "document_no", "title", "deliverable", "equipment", "system"],
        how="inner",
    ).merge(
        hybrid_df,
        on=["row_idx", "source_file", "document_no", "title", "deliverable", "equipment", "system"],
        how="inner",
    )

    for mode in ("text", "structured", "hybrid"):
        for field in SCORE_FIELDS:
            column = f"{mode}_{field}"
            merged[column] = pd.to_numeric(merged[column], errors="coerce")

    merged["row_label"] = merged.apply(make_row_label, axis=1)
    for mode in ("structured", "hybrid"):
        merged[f"{mode}_delta_adjusted"] = (
            merged[f"{mode}_{PRIMARY_SCORE}"] - merged[f"text_{PRIMARY_SCORE}"]
        )
        merged[f"{mode}_delta_rrf"] = (
            merged[f"{mode}_activity_match_rrf_score"] - merged["text_activity_match_rrf_score"]
        )
        merged[f"{mode}_activity_changed"] = (
            merged[f"{mode}_activity_name"].fillna("").astype(str).str.strip()
            != merged["text_activity_name"].fillna("").astype(str).str.strip()
        )
    return merged


def make_row_label(row: pd.Series) -> str:
    document_no = str(row.get("document_no") or "").strip()
    title = str(row.get("title") or "").strip()
    if document_no:
        return f"{document_no} | {title}"
    return title


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    baseline = df["text_activity_match_adjusted_score"]

    rows.append(
        {
            "mode": "text",
            "label": MODE_LABELS["text"],
            "rows_total": len(df),
            "score_available_rows": int(baseline.notna().sum()),
            "score_available_pct": round(100.0 * baseline.notna().mean(), 2),
            "mean_adjusted_score": round(float(baseline.mean()), 4),
            "median_adjusted_score": round(float(baseline.median()), 4),
            "p10_adjusted_score": round(float(baseline.quantile(0.10)), 4),
            "p90_adjusted_score": round(float(baseline.quantile(0.90)), 4),
            "mean_delta_vs_text": 0.0,
            "median_delta_vs_text": 0.0,
            "positive_delta_rows": len(df),
            "negative_delta_rows": 0,
            "zero_delta_rows": 0,
            "activity_changed_rows": 0,
        }
    )

    for mode in ("structured", "hybrid"):
        score = df[f"{mode}_{PRIMARY_SCORE}"]
        delta = df[f"{mode}_delta_adjusted"]
        comparable = delta.notna()
        comparable_delta = delta[comparable]
        rows.append(
            {
                "mode": mode,
                "label": MODE_LABELS[mode],
                "rows_total": len(df),
                "score_available_rows": int(score.notna().sum()),
                "score_available_pct": round(100.0 * score.notna().mean(), 2),
                "mean_adjusted_score": round(float(score.mean()), 4),
                "median_adjusted_score": round(float(score.median()), 4),
                "p10_adjusted_score": round(float(score.quantile(0.10)), 4),
                "p90_adjusted_score": round(float(score.quantile(0.90)), 4),
                "mean_delta_vs_text": round(float(comparable_delta.mean()), 4),
                "median_delta_vs_text": round(float(comparable_delta.median()), 4),
                "positive_delta_rows": int((comparable_delta > 0).sum()),
                "negative_delta_rows": int((comparable_delta < 0).sum()),
                "zero_delta_rows": int((comparable_delta == 0).sum()),
                "activity_changed_rows": int(df[f"{mode}_activity_changed"].sum()),
            }
        )
    return pd.DataFrame(rows)


def write_report(summary_df: pd.DataFrame, df: pd.DataFrame, out_dir: Path) -> None:
    lines = [
        "# Activity Score Gap Report",
        "",
        "This report compares the selected activity-match score per document row.",
        "It does not compare the full 4039-activity score curve because the bench outputs only store the chosen activity's scores.",
        "",
        "## Score availability and central tendency",
        summary_df.to_markdown(index=False),
        "",
    ]

    for mode in ("structured", "hybrid"):
        delta = df[f"{mode}_delta_adjusted"].dropna()
        if delta.empty:
            continue
        lines += [
            f"## {MODE_LABELS[mode]} vs Text",
            f"- comparable rows: {len(delta)} / {len(df)}",
            f"- improved rows (`delta > 0`): {(delta > 0).sum()}",
            f"- worsened rows (`delta < 0`): {(delta < 0).sum()}",
            f"- same score rows: {(delta == 0).sum()}",
            f"- mean delta: {delta.mean():.4f}",
            f"- median delta: {delta.median():.4f}",
            f"- p10 / p90 delta: {delta.quantile(0.10):.4f} / {delta.quantile(0.90):.4f}",
            f"- activity changed: {int(df[f'{mode}_activity_changed'].sum())}",
            "",
        ]

    reason_df = reason_summary(df, "hybrid").head(12)
    if not reason_df.empty:
        lines += [
            "## Hybrid score delta by resolution reason",
            reason_df.to_markdown(index=False),
            "",
        ]

    (out_dir / "score_gap_report.md").write_text("\n".join(lines), encoding="utf-8")


def reason_summary(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    reason_col = f"{mode}_resolution_reason"
    delta_col = f"{mode}_delta_adjusted"
    tmp = df[[reason_col, delta_col]].copy()
    tmp[reason_col] = tmp[reason_col].fillna("").replace("", "EMPTY")
    grouped = tmp.groupby(reason_col, dropna=False)[delta_col]
    summary = grouped.agg(["count", "mean", "median"])
    summary = summary.reset_index().rename(columns={reason_col: "resolution_reason"})
    return summary.sort_values(["count", "median"], ascending=[False, False])


def plot_histogram(df: pd.DataFrame, out_path: Path) -> None:
    plt = get_plt()
    plt.figure(figsize=(11, 6))
    bins = 50
    for mode, color in (("structured", "#d95f02"), ("hybrid", "#1b9e77")):
        delta = df[f"{mode}_delta_adjusted"].dropna()
        if delta.empty:
            continue
        plt.hist(delta, bins=bins, alpha=0.45, label=MODE_LABELS[mode], color=color)
    plt.axvline(0.0, color="black", linewidth=1.2, linestyle="--")
    plt.title("Activity Score Delta vs Text Resolver")
    plt.xlabel("Adjusted score delta relative to text")
    plt.ylabel("Row count")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()


def plot_ecdf(df: pd.DataFrame, out_path: Path) -> None:
    plt = get_plt()
    plt.figure(figsize=(11, 6))
    for mode, color in (("structured", "#d95f02"), ("hybrid", "#1b9e77")):
        delta = df[f"{mode}_delta_adjusted"].dropna().sort_values()
        if delta.empty:
            continue
        y = [(idx + 1) / len(delta) for idx in range(len(delta))]
        plt.plot(delta, y, label=MODE_LABELS[mode], color=color, linewidth=2)
    plt.axvline(0.0, color="black", linewidth=1.2, linestyle="--")
    plt.title("Cumulative View of Activity Score Delta")
    plt.xlabel("Adjusted score delta relative to text")
    plt.ylabel("Cumulative share of rows")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()


def plot_absolute_box(df: pd.DataFrame, out_path: Path) -> None:
    plt = get_plt()
    data = []
    labels = []
    colors = ["#4c78a8", "#d95f02", "#1b9e77"]
    for mode in ("text", "structured", "hybrid"):
        score = df[f"{mode}_{PRIMARY_SCORE}"].dropna()
        if score.empty:
            continue
        data.append(score.tolist())
        labels.append(MODE_LABELS[mode])

    fig, ax = plt.subplots(figsize=(10, 6))
    box = ax.boxplot(data, tick_labels=labels, patch_artist=True, showfliers=False)
    for patch, color in zip(box["boxes"], colors[: len(box["boxes"])], strict=False):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax.set_title("Selected Activity Adjusted Score by Resolver Mode")
    ax.set_ylabel("Adjusted score")
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def plot_reason_box(df: pd.DataFrame, mode: str, out_path: Path) -> None:
    plt = get_plt()
    reason_col = f"{mode}_resolution_reason"
    delta_col = f"{mode}_delta_adjusted"
    tmp = df[[reason_col, delta_col]].dropna(subset=[delta_col]).copy()
    tmp[reason_col] = tmp[reason_col].fillna("").replace("", "EMPTY")
    order = tmp[reason_col].value_counts().head(8).index.tolist()
    series = [tmp.loc[tmp[reason_col] == reason, delta_col].tolist() for reason in order]
    if not series:
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    box = ax.boxplot(series, tick_labels=order, patch_artist=True, showfliers=False)
    for patch in box["boxes"]:
        patch.set_facecolor("#1b9e77")
        patch.set_alpha(0.55)
    ax.axhline(0.0, color="black", linewidth=1.1, linestyle="--")
    ax.set_title(f"{MODE_LABELS[mode]}: score delta by resolution reason")
    ax.set_ylabel("Adjusted score delta relative to text")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def truncate_label(value: str, limit: int = 72) -> str:
    value = value.replace("\n", " ").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def plot_top_deltas(df: pd.DataFrame, mode: str, top_n: int, out_path: Path) -> None:
    plt = get_plt()
    delta_col = f"{mode}_delta_adjusted"
    score_col = f"{mode}_{PRIMARY_SCORE}"
    tmp = df.dropna(subset=[delta_col, score_col, "text_activity_match_adjusted_score"]).copy()
    if tmp.empty:
        return
    tmp["abs_delta"] = tmp[delta_col].abs()
    tmp = tmp.sort_values("abs_delta", ascending=False).head(top_n).sort_values(delta_col)
    labels = [truncate_label(label) for label in tmp["row_label"]]
    y_positions = range(len(tmp))

    fig_h = max(7, 0.32 * len(tmp) + 1.5)
    fig, ax = plt.subplots(figsize=(14, fig_h))
    for y, (_, row) in zip(y_positions, tmp.iterrows(), strict=True):
        base_score = float(row["text_activity_match_adjusted_score"])
        cand_score = float(row[score_col])
        color = "#1b9e77" if cand_score >= base_score else "#d95f02"
        ax.plot([base_score, cand_score], [y, y], color=color, linewidth=2.4, alpha=0.9)
        ax.scatter(base_score, y, color="#4c78a8", s=30, zorder=3)
        ax.scatter(cand_score, y, color=color, s=34, zorder=3)

    ax.set_yticks(list(y_positions))
    ax.set_yticklabels(labels)
    ax.set_xlabel("Adjusted score")
    ax.set_title(f"Top {len(tmp)} row-level score shifts: {MODE_LABELS[mode]} vs Text")
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    ax.legend(
        handles=[
            plt.Line2D([0], [0], color="#4c78a8", marker="o", linestyle="", label="Text"),
            plt.Line2D([0], [0], color="#1b9e77", marker="o", linestyle="", label="Higher than text"),
            plt.Line2D([0], [0], color="#d95f02", marker="o", linestyle="", label="Lower than text"),
        ],
        loc="lower right",
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def ensure_out_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    mpl_config = path / ".mplconfig"
    mpl_config.mkdir(exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_config))


def main() -> None:
    args = parse_args()
    ensure_out_dir(args.out_dir)

    text_df = load_mode(args.text_csv, "text")
    structured_df = load_mode(args.structured_csv, "structured")
    hybrid_df = load_mode(args.hybrid_csv, "hybrid")
    comparison_df = build_comparison(text_df, structured_df, hybrid_df)

    summary_df = summarize(comparison_df)
    summary_df.to_csv(args.out_dir / "score_gap_summary.csv", index=False, encoding="utf-8-sig")
    reason_summary(comparison_df, "hybrid").to_csv(
        args.out_dir / "score_gap_reason_summary_hybrid.csv",
        index=False,
        encoding="utf-8-sig",
    )
    write_report(summary_df, comparison_df, args.out_dir)

    plot_histogram(comparison_df, args.out_dir / "activity_score_delta_hist.png")
    plot_ecdf(comparison_df, args.out_dir / "activity_score_delta_ecdf.png")
    plot_absolute_box(comparison_df, args.out_dir / "activity_score_absolute_box.png")
    plot_reason_box(comparison_df, "hybrid", args.out_dir / "activity_score_reason_box_hybrid.png")
    plot_top_deltas(
        comparison_df,
        "structured",
        args.top_n,
        args.out_dir / "activity_score_top_deltas_structured.png",
    )
    plot_top_deltas(
        comparison_df,
        "hybrid",
        args.top_n,
        args.out_dir / "activity_score_top_deltas_hybrid.png",
    )

    print(f"Wrote score-gap visuals to {args.out_dir}")


if __name__ == "__main__":
    main()
