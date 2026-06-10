#!/usr/bin/env python3
"""
Review Schedule JSON Output Metrics
==================================

Purpose:
    Read a schedule/output JSON file and generate review charts + summary tables
    for business/QA evaluation.

Recommended charts:
    1. Date range status distribution
    2. Schedule quality status distribution
    3. Submission type distribution
    4. Rule guard status distribution
    5. Activity phase/scope status comparison
    6. Score histograms for rule/activity confidence fields
    7. Top schedule quality reasons
    8. Usability bucket summary

Usage:
    python review_schedule_json_metrics.py input.json
    python review_schedule_json_metrics.py input.json --out-dir review_report
    python scripts/review_schedule_json_metrics.py output/schedule_service/generate/generated_schedule_Fadhili_MDL_classified_ntp2024-03-01.json --out-dir output/schedule_service/bench

Dependencies:
    pip install pandas matplotlib

Notes:
    - The script is defensive: missing columns are skipped instead of crashing.
    - Percentages are calculated against total rows.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import pandas as pd


# -----------------------------
# Config
# -----------------------------
STATUS_ORDER = [
    "generated",
    "needs_review",
    "missing_fa",
    "blocked_missing_date",
    "blocked_rule",
    "blocked_activity",
    "blocked_rule_activity",
    "blocked_no_rule",
    "no_rule",
    "skip",
]

NUMERIC_COLUMNS = [
    "rule_match_token_score",
    "rule_match_semantic_score",
    "rule_match_hybrid_score",
    "rule_match_final_score",
    "activity_match_semantic_score",
    "activity_match_rrf_score",
    "activity_match_adjusted_score",
    "date_range_confidence",
    "schedule_confidence",
]


def load_json(path: Path) -> pd.DataFrame:
    """Load a JSON array file into a DataFrame."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Expected top-level JSON to be a list of objects.")
    df = pd.DataFrame(data)
    return normalize_dataframe(df)


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize empty strings and numeric columns."""
    df = df.copy()

    # Keep object columns readable; convert blanks to explicit label for charts.
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].fillna("").astype(str).str.strip()

    # Convert known numeric fields safely.
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")

    return df


def pct(part: int | float, total: int | float) -> float:
    return round((part / total * 100), 2) if total else 0.0


def counts_table(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Return count + percentage table for one categorical column."""
    if col not in df.columns:
        return pd.DataFrame(columns=[col, "count", "percent"])

    total = len(df)
    s = df[col].replace("", "EMPTY").fillna("EMPTY")
    out = (
        s.value_counts(dropna=False)
        .rename_axis(col)
        .reset_index(name="count")
    )
    out["percent"] = (out["count"] / total * 100).round(2)
    return out


def save_bar_chart(table: pd.DataFrame, label_col: str, value_col: str, title: str, path: Path, *, horizontal: bool = True) -> None:
    """Save a clean bar chart from a summary table."""
    if table.empty:
        return

    fig_height = max(4, min(12, 0.42 * len(table) + 2))
    fig_width = 11
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    labels = table[label_col].astype(str).tolist()
    values = table[value_col].tolist()

    if horizontal:
        ax.barh(labels, values)
        ax.invert_yaxis()
        ax.set_xlabel(value_col.capitalize())
        for i, v in enumerate(values):
            ax.text(v, i, f" {v}", va="center", fontsize=9)
    else:
        ax.bar(labels, values)
        ax.set_ylabel(value_col.capitalize())
        ax.tick_params(axis="x", rotation=35)
        for i, v in enumerate(values):
            ax.text(i, v, f"{v}", ha="center", va="bottom", fontsize=9)

    ax.set_title(title)
    ax.grid(axis="x" if horizontal else "y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_pie_chart(table: pd.DataFrame, label_col: str, value_col: str, title: str, path: Path) -> None:
    """Save a pie chart for small part-to-whole distributions."""
    if table.empty:
        return

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.pie(
        table[value_col],
        labels=table[label_col].astype(str),
        autopct="%1.1f%%",
        startangle=90,
        pctdistance=0.82,
    )
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_histogram(df: pd.DataFrame, col: str, path: Path) -> None:
    """Save histogram for numeric score columns."""
    if col not in df.columns:
        return
    values = df[col].dropna()
    if values.empty:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(values, bins=20)
    ax.set_title(f"Distribution of {col}")
    ax.set_xlabel(col)
    ax.set_ylabel("Count")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_phase_scope_comparison(df: pd.DataFrame, out_dir: Path) -> None:
    """Compare activity phase status and scope status in one grouped bar chart."""
    cols = ["activity_match_phase_status", "activity_match_scope_status"]
    if not all(c in df.columns for c in cols):
        return

    phase = counts_table(df, cols[0]).rename(columns={cols[0]: "status", "count": "phase_count"})[["status", "phase_count"]]
    scope = counts_table(df, cols[1]).rename(columns={cols[1]: "status", "count": "scope_count"})[["status", "scope_count"]]
    merged = phase.merge(scope, on="status", how="outer").fillna(0)
    merged[["phase_count", "scope_count"]] = merged[["phase_count", "scope_count"]].astype(int)
    merged = merged.sort_values(["phase_count", "scope_count"], ascending=False)

    fig, ax = plt.subplots(figsize=(11, max(4, 0.45 * len(merged) + 2)))
    y = range(len(merged))
    bar_h = 0.38
    ax.barh([i - bar_h / 2 for i in y], merged["phase_count"], height=bar_h, label="Phase status")
    ax.barh([i + bar_h / 2 for i in y], merged["scope_count"], height=bar_h, label="Scope status")
    ax.set_yticks(list(y))
    ax.set_yticklabels(merged["status"].astype(str))
    ax.invert_yaxis()
    ax.set_xlabel("Count")
    ax.set_title("Activity match phase vs scope status")
    ax.grid(axis="x", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "activity_phase_vs_scope_status.png", dpi=160)
    plt.close(fig)


def explode_reasons(df: pd.DataFrame) -> pd.DataFrame:
    """Split semicolon-separated schedule quality reasons into rows."""
    if "schedule_quality_reasons" not in df.columns:
        return pd.DataFrame(columns=["reason", "count", "percent"])

    reasons: list[str] = []
    for raw in df["schedule_quality_reasons"].fillna("").astype(str):
        for item in re.split(r";\s*", raw):
            item = item.strip()
            if item:
                reasons.append(item)

    if not reasons:
        return pd.DataFrame(columns=["reason", "count", "percent"])

    total = len(df)
    out = pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")
    out["percent"] = (out["count"] / total * 100).round(2)
    return out


def build_usability_bucket(df: pd.DataFrame) -> pd.DataFrame:
    """
    Business-oriented bucket:
    - Usable generated: date_range_status == generated
    - Skip: date_range_status == skip
    - Partial/missing date: missing_fa or blocked_missing_date
    - Blocked by rule/activity: blocked_* except missing date
    - No rule: no_rule or blocked_no_rule
    """
    status = df.get("date_range_status", pd.Series([""] * len(df))).fillna("").astype(str)
    quality = df.get("schedule_quality_status", pd.Series([""] * len(df))).fillna("").astype(str)

    buckets = []
    for ds, qs in zip(status, quality):
        if ds == "generated":
            buckets.append("Usable/generated date range")
        elif ds == "skip" or qs == "skip":
            buckets.append("SKIP / not required")
        elif ds in {"missing_fa", "blocked_missing_date"} or qs == "blocked_missing_date":
            buckets.append("Partial / missing FA date")
        elif ds in {"no_rule", "blocked_no_rule"} or qs == "blocked_no_rule":
            buckets.append("No usable rule")
        elif ds.startswith("blocked") or qs.startswith("blocked"):
            buckets.append("Blocked by rule/activity quality")
        else:
            buckets.append("Other / review")

    tmp = pd.DataFrame({"bucket": buckets})
    return counts_table(tmp, "bucket")


def save_markdown_report(df: pd.DataFrame, out_dir: Path, summary_tables: dict[str, pd.DataFrame]) -> None:
    total = len(df)
    generated = int((df.get("date_range_status", pd.Series(dtype=str)) == "generated").sum()) if "date_range_status" in df.columns else 0
    skip = int((df.get("date_range_status", pd.Series(dtype=str)) == "skip").sum()) if "date_range_status" in df.columns else 0
    no_rule = int(df.get("date_range_status", pd.Series(dtype=str)).isin(["no_rule"]).sum()) if "date_range_status" in df.columns else 0
    missing_fa = int(df.get("date_range_status", pd.Series(dtype=str)).isin(["missing_fa"]).sum()) if "date_range_status" in df.columns else 0

    lines = [
        "# Schedule JSON Review Report",
        "",
        f"Total rows: **{total:,}**",
        "",
        "## Key metrics",
        f"- Generated usable date ranges: **{generated:,} / {total:,} ({pct(generated, total)}%)**",
        f"- SKIP rows: **{skip:,} / {total:,} ({pct(skip, total)}%)**",
        f"- Missing FA rows: **{missing_fa:,} / {total:,} ({pct(missing_fa, total)}%)**",
        f"- No-rule rows: **{no_rule:,} / {total:,} ({pct(no_rule, total)}%)**",
        "",
        "## Interpretation",
        "- Use `date_range_status` / `schedule_quality_status` as the main business-readiness view.",
        "- Use rule-match charts to evaluate classification/rule matching quality.",
        "- Use activity phase/scope charts to diagnose why schedule activity matching blocks date generation.",
        "- Use score histograms to choose thresholds and identify low-confidence ranges.",
        "",
    ]

    for name, table in summary_tables.items():
        lines.append(f"## {name}")
        if table.empty:
            lines.append("No data.")
        else:
            lines.append(table.to_markdown(index=False))
        lines.append("")

    (out_dir / "review_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate review charts from schedule JSON output.")
    parser.add_argument("json_path", type=Path, help="Path to JSON file, expected as a list of objects.")
    parser.add_argument("--out-dir", type=Path, default=Path("review_output"), help="Directory for charts and summary files.")
    args = parser.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_json(args.json_path)
    total = len(df)
    print(f"Loaded {total:,} rows and {len(df.columns)} columns")

    # Save normalized copy for further review.
    df.to_csv(out_dir / "normalized_output.csv", index=False, encoding="utf-8-sig")

    summary_tables: dict[str, pd.DataFrame] = {}

    # Main categorical charts.
    categorical_charts = [
        ("date_range_status", "Date range status distribution", "date_range_status.png"),
        ("schedule_quality_status", "Schedule quality status distribution", "schedule_quality_status.png"),
        ("submission_type", "Submission type distribution", "submission_type.png"),
        ("rule_match_guard_status", "Rule guard status distribution", "rule_guard_status.png"),
        ("rule_match_family_status", "Rule family status distribution", "rule_family_status.png"),
        ("rule_match_subtype_status", "Rule subtype status distribution", "rule_subtype_status.png"),
        ("rule_match_scope_status", "Rule scope status distribution", "rule_scope_status.png"),
        ("activity_match_phase_status", "Activity phase status distribution", "activity_phase_status.png"),
        ("activity_match_scope_status", "Activity scope status distribution", "activity_scope_status.png"),
    ]

    for col, title, filename in categorical_charts:
        if col not in df.columns:
            continue
        table = counts_table(df, col)
        summary_tables[title] = table
        table.to_csv(out_dir / f"{col}_summary.csv", index=False, encoding="utf-8-sig")
        horizontal = len(table) >= 6
        save_bar_chart(table, col, "count", title, out_dir / filename, horizontal=horizontal)

    # Pie chart is good for submission type because it is a small part-to-whole category.
    if "submission_type" in df.columns:
        save_pie_chart(counts_table(df, "submission_type"), "submission_type", "count", "Submission type share", out_dir / "submission_type_pie.png")

    # Business usability bucket.
    usability = build_usability_bucket(df)
    summary_tables["Business usability bucket"] = usability
    usability.to_csv(out_dir / "business_usability_bucket.csv", index=False, encoding="utf-8-sig")
    save_bar_chart(usability, "bucket", "count", "Business usability bucket", out_dir / "business_usability_bucket.png", horizontal=True)

    # Reason analysis.
    reasons = explode_reasons(df).head(20)
    summary_tables["Top schedule quality reasons"] = reasons
    reasons.to_csv(out_dir / "top_schedule_quality_reasons.csv", index=False, encoding="utf-8-sig")
    save_bar_chart(reasons, "reason", "count", "Top schedule quality reasons", out_dir / "top_schedule_quality_reasons.png", horizontal=True)

    # Score histograms.
    for col in NUMERIC_COLUMNS:
        save_histogram(df, col, out_dir / f"hist_{col}.png")

    # Activity phase/scope comparison.
    save_phase_scope_comparison(df, out_dir)

    # Markdown summary.
    save_markdown_report(df, out_dir, summary_tables)

    print(f"Done. Report files saved to: {out_dir.resolve()}")
    print("Recommended first read: review_report.md")


if __name__ == "__main__":
    main()
