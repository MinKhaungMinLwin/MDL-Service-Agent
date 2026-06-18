"""Unit tests for the schedule eval scorer and review builder (offline, no Azure)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from evaluation_service.schedule_eval import review_from_generated as rfg
from evaluation_service.schedule_eval import score as sc


def _promotable_json_row(**overrides: str) -> dict[str, str]:
    """A generated-JSON row that satisfies the full promotable gate by default."""
    row = {
        "document_no": "DOC-1",
        "title": "P&ID for Main Steam System",
        "deliverable": "P&I DIAGRAM",
        "equipment": "MAIN STEAM SYSTEM",
        "system": "",
        "matched_rule": "P&ID",
        "matched_rule_keyword": "P&ID",
        "submission_type": "FA",
        "matched_activity_id": "ACT-1",
        "matched_activity_name": "(Steam System) P&ID & System Design",
        "matched_activity_wbs_path": "Plant > Steam",
        "fa_recommended": "2024-08-01",
        "fc_recommended": "2024-10-01",
        "rule_match_scope_status": "rule_generic",
        "rule_match_family_status": "match",
        "rule_match_subtype_status": "match",
        "rule_match_semantic_score": "0.71",
        "activity_match_scope_status": "match",
        "activity_match_scope_source": "query",
        "activity_match_effective_scope": "steam",
        "activity_match_phase_status": "match",
        "date_range_status": "generated",
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------- is_promotable

def test_is_promotable_true_for_full_gate():
    assert sc.is_promotable(_promotable_json_row()) is True


def test_is_promotable_false_when_any_condition_breaks():
    assert sc.is_promotable(_promotable_json_row(rule_match_scope_status="match")) is False
    assert sc.is_promotable(_promotable_json_row(rule_match_family_status="compatible")) is False
    assert sc.is_promotable(_promotable_json_row(rule_match_semantic_score="0.40")) is False
    assert sc.is_promotable(_promotable_json_row(activity_match_scope_status="query_unscoped")) is False
    assert sc.is_promotable(_promotable_json_row(activity_match_scope_source="rule")) is False
    assert sc.is_promotable(_promotable_json_row(activity_match_effective_scope="steam|hrsg")) is False
    assert sc.is_promotable(_promotable_json_row(activity_match_phase_status="compatible")) is False
    assert sc.is_promotable(_promotable_json_row(date_range_status="blocked_activity")) is False


# ------------------------------------------------------------- label resolution / scoring

def test_human_label_overrides_llm_silver():
    row = {"llm_rule_ok": "no", "human_rule_ok": "yes"}
    assert sc._effective_label(row, "rule_ok") == "yes"


def test_llm_label_used_when_no_human():
    row = {"llm_activity_ok": "partial", "human_activity_ok": ""}
    assert sc._effective_label(row, "activity_ok") == "partial"


def test_bucket_accuracy_counts_yes_only_and_end_to_end():
    rows = [
        {"human_rule_ok": "yes", "human_activity_ok": "yes"},      # both yes
        {"human_rule_ok": "yes", "human_activity_ok": "partial"},  # rule yes, act partial
        {"llm_rule_ok": "no", "llm_activity_ok": "yes"},           # rule no, act yes (silver)
        {"human_notes": "x"},                                      # unlabeled -> excluded
    ]
    bucket = sc._bucket_accuracy(rows)
    assert bucket["total"] == 4
    assert bucket["labeled"] == 3
    assert bucket["rule_yes"] == 2
    assert bucket["activity_yes"] == 2
    assert bucket["activity_partial"] == 1
    assert bucket["end_to_end_yes"] == 1
    assert bucket["rule_accuracy"] == round(2 / 3, 4)


# ----------------------------------------------------------------- review builder

def test_build_tags_promotable_and_control(tmp_path: Path):
    rows = [_promotable_json_row(document_no=f"P{i}", title=f"P&ID doc {i}") for i in range(5)]
    rows += [
        _promotable_json_row(
            document_no=f"C{i}", title=f"Plan doc {i}", deliverable="PLAN",
            activity_match_scope_status="query_unscoped",  # breaks gate -> control
        )
        for i in range(3)
    ]
    gen = tmp_path / "gen.json"
    gen.write_text(json.dumps(rows), encoding="utf-8")

    review = rfg.build(gen, sample_size=10, control_size=10, seed=1)
    gates = [r["promotion_gate"] for r in review]
    assert gates.count("promotable") == 5
    assert gates.count("control") == 3
    # predicted fields are sourced from the JSON, human columns are blank
    sample = review[0]
    assert sample["predicted_activity_id"] in {"ACT-1"}
    assert sample["human_rule_ok"] == ""


def test_build_skips_blocked_rows(tmp_path: Path):
    rows = [
        _promotable_json_row(document_no="G1"),
        _promotable_json_row(document_no="B1", date_range_status="blocked_activity"),
    ]
    gen = tmp_path / "gen.json"
    gen.write_text(json.dumps(rows), encoding="utf-8")
    review = rfg.build(gen, sample_size=10, control_size=10, seed=1)
    # blocked row is neither generated nor fi_complete -> excluded entirely
    assert len(review) == 1
    assert review[0]["promotion_gate"] == "promotable"


# ----------------------------------------------------------------- end-to-end score join

def test_score_slices_by_promotable_membership(tmp_path: Path):
    gen_rows = [
        _promotable_json_row(document_no="P1", title="P&ID A"),
        _promotable_json_row(document_no="P2", title="P&ID B"),
        _promotable_json_row(document_no="C1", title="Plan C", activity_match_scope_status="query_unscoped"),
    ]
    gen = tmp_path / "gen.json"
    gen.write_text(json.dumps(gen_rows), encoding="utf-8")

    review = tmp_path / "review.csv"
    header = ["document_no", "title", "deliverable_norm", "human_rule_ok", "human_activity_ok"]
    with review.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows([
            {"document_no": "P1", "title": "P&ID A", "deliverable_norm": "P&ID",
             "human_rule_ok": "yes", "human_activity_ok": "yes"},
            {"document_no": "P2", "title": "P&ID B", "deliverable_norm": "P&ID",
             "human_rule_ok": "yes", "human_activity_ok": "no"},
            {"document_no": "C1", "title": "Plan C", "deliverable_norm": "PLAN",
             "human_rule_ok": "no", "human_activity_ok": "no"},
        ])

    report = sc.score(review, generated_path=gen)
    assert report["promotable_in_review"] == 2
    assert report["promotable"]["activity_yes"] == 1
    assert report["promotable"]["activity_accuracy"] == 0.5
    assert report["non_promotable"]["activity_yes"] == 0
