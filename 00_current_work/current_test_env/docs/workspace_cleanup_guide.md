# Workspace Cleanup Guide

현재 메인 흐름을 남기고 과거 실험 파일을 `archive`로 이동하기 위한 기준입니다.

유지 대상:

- `classify_mdl_v5-2.py`
- `build_standard_mdl.py`
- `build_package_grouped_llm_pilot.py`
- `build_vendor_package_master_candidate.py`
- `data/`
- `docs/mdl_project_handoff_*.md`
- `output/*_MDL_classified.csv`
- `output/standard_mdl/vendor_package_master_candidate/`
- `output/standard_mdl/package_grouped_llm_vendor_acc_hrsg_dcs_l12_forced_l3_free/`
- `output/standard_mdl/package_grouped_llm_epc_l12_forced_l3_free/`

아카이브 대상:

- `output/acc/`
- `output/itb_sections/`
- `output/output_itb_*.csv`
- `output/output_keyword_doc_section_title_matches_*.csv`
- `output/backup_local_untracked/`
- `output/standard_mdl` 하위의 과거 비교/실험 산출물
- 필요 시 legacy ITB/ACC 스크립트

실행:

```bash
cd 00_current_work/current_test_env
python3 organize_workspace_archive.py
```

실제 이동:

```bash
cd 00_current_work/current_test_env
python3 organize_workspace_archive.py --apply
```

legacy 스크립트까지 이동:

```bash
cd 00_current_work/current_test_env
python3 organize_workspace_archive.py --apply --include-legacy-scripts
```

기본 동작은 `dry-run`입니다. `--apply`를 주기 전에는 아무 파일도 이동하지 않습니다.
