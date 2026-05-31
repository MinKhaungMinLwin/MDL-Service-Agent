# Project Folder Structure

This repository keeps runtime code, reference documents, source data, and generated outputs in separate locations.

## Main Locations

| Path | Purpose |
| --- | --- |
| `src/` | Runtime source code, prompts packaged with services, API routes, and docs. |
| `tests/` | Unit tests for MDL, ITB, matching, and schedule behavior. |
| `03_reference_docs/` | Proposals, prompt feedback, vendor docs, and system notes. |
| `04_data/current_test_env/data/` | Current MDL workbooks and parsed ITB chunk JSON used by local workflows. |
| `04_data/sample_documents/project_samples/` | Project sample ITB/MDL source documents. |
| `04_data/source_archives/SourceData/` | Original SourceData zip archives. |
| `04_data/schedule_sources/` | Raw/processed guide schedule files and validation rules. |
| `output/current_test_env/` | Generated MDL classification, ITB extraction, and ITB-to-MDL matching outputs. |
| `output/schedule_service/` | Generated schedule API/CLI outputs. |
| `01_legacy_poc/` | First POC code kept as historical reference only. |
| `02_experiments/` | Experiment and prompt-test history. |
| `05_archives/` | Archived backups and compressed historical artifacts. |

## Current Workflow

Runtime Python code should live in `src/`, not under `00_current_work/`.

Use these CLI commands from the repository root:

```powershell
uv run mdl-classify
uv run mdl-ingest
uv run itb-extract --section 7
uv run itb-match
```

See `src/docs/workflows.md` for command details and default paths.
