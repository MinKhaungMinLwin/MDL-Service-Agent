"""Archive legacy MDL/ITB experiment files while preserving the current flow.

Default mode is dry-run. Use ``--apply`` to move files/directories into
``output/archive/<tag>/`` and ``archive/<tag>/``.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
ROOT_ARCHIVE_DIR = BASE_DIR / "archive"


@dataclass(frozen=True)
class ArchiveRule:
    source: str
    target_group: str
    reason: str


ARCHIVE_RULES = [
    ArchiveRule("output/acc", "legacy_acc_poc", "Legacy ACC-only POC outputs."),
    ArchiveRule("output/itb_sections", "legacy_itb_section_poc", "Legacy section-based ITB outputs."),
    ArchiveRule("output/backup_local_untracked", "legacy_backups", "Local backup outputs not used in current flow."),
    ArchiveRule("output/output_itb_all_strict.csv", "legacy_itb_keyword_outputs", "Legacy ITB keyword output."),
    ArchiveRule("output/output_itb_all_strict_fast.csv", "legacy_itb_keyword_outputs", "Legacy ITB keyword output."),
    ArchiveRule("output/output_itb_keyword_sections.csv", "legacy_itb_keyword_outputs", "Legacy ITB keyword output."),
    ArchiveRule("output/output_itb_keyword_sections_all_strict.csv", "legacy_itb_keyword_outputs", "Legacy ITB keyword output."),
    ArchiveRule("output/output_itb_keyword_sections_strict.csv", "legacy_itb_keyword_outputs", "Legacy ITB keyword output."),
    ArchiveRule("output/output_itb_tokens_all_strict_fast.csv", "legacy_itb_keyword_outputs", "Legacy ITB keyword output."),
    ArchiveRule("output/output_keyword_doc_section_title_matches_fadhili_all_strict.csv", "legacy_itb_keyword_outputs", "Legacy ITB keyword output."),
    ArchiveRule("output/output_keyword_doc_section_title_matches_fadhili_strict.csv", "legacy_itb_keyword_outputs", "Legacy ITB keyword output."),
    ArchiveRule("output/Fadhili_MDL_classified_backup_before_study_survey.csv", "classified_backups", "Backup classified CSV."),
    ArchiveRule("output/Grati_MDL_classified_backup_before_study_survey.csv", "classified_backups", "Backup classified CSV."),
    ArchiveRule("output/Karabatan_MDL_classified_backup_before_study_survey.csv", "classified_backups", "Backup classified CSV."),
    ArchiveRule("output/Muara Tawar_MDL_classified_backup_before_study_survey.csv", "classified_backups", "Backup classified CSV."),
    ArchiveRule("output/R&N_MDL_classified_backup_before_260612.csv", "classified_backups", "Backup classified CSV."),
    ArchiveRule("output/Turkistan_MDL_classified_backup_before_study_survey.csv", "classified_backups", "Backup classified CSV."),
    ArchiveRule("output/Ukudu_MDL_classified_backup_before_study_survey.csv", "classified_backups", "Backup classified CSV."),
    ArchiveRule("output/standard_mdl/llm_first_test", "standard_mdl_experiments", "LLM-first comparison experiment."),
    ArchiveRule("output/standard_mdl/package_grouped_llm_pilot", "standard_mdl_experiments", "Early package-grouped pilot."),
    ArchiveRule("output/standard_mdl/package_grouped_llm_all_projects", "standard_mdl_experiments", "Intermediate package-grouped experiment."),
    ArchiveRule("output/standard_mdl/package_grouped_llm_all_projects_l123_title_regen_epc20", "standard_mdl_experiments", "Intermediate package-grouped experiment."),
    ArchiveRule("output/standard_mdl/package_grouped_llm_all_projects_l12_forced_l3_free_epc20", "standard_mdl_experiments", "Intermediate package-grouped experiment."),
    ArchiveRule("output/standard_mdl/package_grouped_llm_all_projects_lv1lv2_forced", "standard_mdl_experiments", "Intermediate package-grouped experiment."),
    ArchiveRule("output/standard_mdl/package_grouped_llm_vendor_acc_hrsg_dcs_l12_forced_l3_llm", "standard_mdl_experiments", "Superseded vendor package-grouped experiment."),
    ArchiveRule("output/standard_mdl/pilot_llm_integrated_standard_mdl.csv", "standard_mdl_experiments", "Legacy pilot integrated Standard MDL output."),
    ArchiveRule("output/standard_mdl/pilot_llm_integrated_standard_mdl.xlsx", "standard_mdl_experiments", "Legacy pilot integrated Standard MDL output."),
    ArchiveRule("output/standard_mdl/pilot_llm_merge_audit.csv", "standard_mdl_experiments", "Legacy pilot integrated Standard MDL audit."),
    ArchiveRule("output/standard_mdl/pilot_llm_merge_rejections.csv", "standard_mdl_experiments", "Legacy pilot integrated Standard MDL rejection log."),
    ArchiveRule("output/standard_mdl/pilot_llm_validation_report.csv", "standard_mdl_experiments", "Legacy pilot integrated Standard MDL validation."),
    ArchiveRule("output/standard_mdl/llm_integrated_standard_mdl.csv", "standard_mdl_experiments", "Legacy LLM merge Standard MDL output."),
    ArchiveRule("output/standard_mdl/llm_integrated_standard_mdl.xlsx", "standard_mdl_experiments", "Legacy LLM merge Standard MDL output."),
    ArchiveRule("output/standard_mdl/llm_merge_audit.csv", "standard_mdl_experiments", "Legacy LLM merge audit."),
    ArchiveRule("output/standard_mdl/llm_merge_rejections.csv", "standard_mdl_experiments", "Legacy LLM merge rejection log."),
    ArchiveRule("output/standard_mdl/llm_validation_report.csv", "standard_mdl_experiments", "Legacy LLM merge validation."),
    ArchiveRule("output/standard_mdl/integrated_standard_mdl.csv", "standard_mdl_experiments", "Legacy integrated Standard MDL output."),
    ArchiveRule("output/standard_mdl/integrated_standard_mdl.xlsx", "standard_mdl_experiments", "Legacy integrated Standard MDL output."),
    ArchiveRule("output/standard_mdl/expert_augmentation_audit.csv", "standard_mdl_experiments", "Legacy expert augmentation audit."),
    ArchiveRule("output/standard_mdl/expert_augmentation_validation.csv", "standard_mdl_experiments", "Legacy expert augmentation validation."),
    ArchiveRule("output/standard_mdl/expert_augmented_standard_mdl.csv", "standard_mdl_experiments", "Legacy expert augmentation output."),
    ArchiveRule("output/standard_mdl/expert_augmented_standard_mdl.xlsx", "standard_mdl_experiments", "Legacy expert augmentation output."),
    ArchiveRule("output/standard_mdl/expert_prompt_audit.csv", "standard_mdl_experiments", "Legacy expert prompt audit."),
    ArchiveRule("output/standard_mdl/expert_prompt_standard_mdl.csv", "standard_mdl_experiments", "Legacy expert prompt output."),
    ArchiveRule("output/standard_mdl/expert_prompt_standard_mdl.xlsx", "standard_mdl_experiments", "Legacy expert prompt output."),
    ArchiveRule("output/standard_mdl/expert_prompt_validation.csv", "standard_mdl_experiments", "Legacy expert prompt validation."),
    ArchiveRule("output/standard_mdl/copilot_vs_expert_augmented_comparison.xlsx", "reference_comparisons", "Reference comparison only."),
    ArchiveRule("output/standard_mdl/copilot_vs_expert_prompt_comparison.xlsx", "reference_comparisons", "Reference comparison only."),
    ArchiveRule("output/standard_mdl/copilot_vs_our_llm_mdl_comparison.xlsx", "reference_comparisons", "Reference comparison only."),
]


LEGACY_SCRIPT_RULES = [
    ArchiveRule("activate_documents_by_section.py", "legacy_scripts", "Legacy ITB section activation workflow."),
    ArchiveRule("build_acc_customer_test.py", "legacy_scripts", "Legacy ACC customer test workflow."),
    ArchiveRule("build_acc_document_list.py", "legacy_scripts", "Legacy ACC document list workflow."),
    ArchiveRule("build_itb_keyword_sections.py", "legacy_scripts", "Legacy ITB keyword workflow."),
    ArchiveRule("build_itb_section_registry.py", "legacy_scripts", "Legacy ITB section registry workflow."),
    ArchiveRule("build_llm_first_standard_mdl_test.py", "legacy_scripts", "LLM-first test script kept separate from current main flow."),
    ArchiveRule("compare_copilot_standard_mdl.py", "legacy_scripts", "Reference-only comparison script."),
    ArchiveRule("itb_keyword_extraction_prompt.md", "legacy_scripts", "Legacy ITB extraction prompt."),
    ArchiveRule("itb_keyword_extraction_prompt_strict.md", "legacy_scripts", "Legacy ITB extraction prompt."),
    ArchiveRule("match_itb_advanced.py", "legacy_scripts", "Legacy ITB matching workflow."),
    ArchiveRule("match_itb_core.py", "legacy_scripts", "Legacy ITB matching workflow."),
    ArchiveRule("match_itb_fadhili_only.py", "legacy_scripts", "Legacy ITB matching workflow."),
    ArchiveRule("match_itb_keywords_fadhili_title_filter.py", "legacy_scripts", "Legacy ITB matching workflow."),
    ArchiveRule("save_to_neo4j_test.py", "legacy_scripts", "Legacy Neo4j ingestion helper."),
    ArchiveRule("test_itb_extraction.py", "legacy_scripts", "Legacy script-style test."),
    ArchiveRule("test_vector_filter.py", "legacy_scripts", "Legacy script-style test."),
    ArchiveRule("__pycache__", "workspace_misc", "Python bytecode cache."),
    ArchiveRule("=1.24.0", "workspace_misc", "Accidental artifact file."),
]


def move_path(source: Path, destination: Path, apply: bool) -> str:
    if not source.exists():
        return f"SKIP missing: {source}"
    if destination.exists():
        return f"SKIP exists: {destination}"
    if not apply:
        return f"DRY-RUN move: {source} -> {destination}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return f"MOVED: {source} -> {destination}"


def archive_rules(rules: list[ArchiveRule], tag: str, apply: bool) -> list[str]:
    messages: list[str] = []
    for rule in rules:
        source = BASE_DIR / rule.source
        archive_root = OUTPUT_DIR / "archive" / tag if rule.source.startswith("output/") else ROOT_ARCHIVE_DIR / tag
        destination = archive_root / rule.target_group / source.name
        messages.append(f"# {rule.reason}")
        messages.append(move_path(source, destination, apply))
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive legacy MDL/ITB workspace files.")
    parser.add_argument("--tag", default="2026-06-18_workspace_cleanup", help="Archive tag folder name.")
    parser.add_argument("--apply", action="store_true", help="Perform moves. Default is dry-run.")
    parser.add_argument(
        "--include-legacy-scripts",
        action="store_true",
        help="Also archive legacy scripts and prompts from current_test_env root.",
    )
    args = parser.parse_args()

    messages = archive_rules(ARCHIVE_RULES, args.tag, args.apply)
    if args.include_legacy_scripts:
        messages.extend(archive_rules(LEGACY_SCRIPT_RULES, args.tag, args.apply))

    print("\n".join(messages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
