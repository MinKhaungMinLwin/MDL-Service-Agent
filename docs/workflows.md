# Workflow Commands

Run commands from the repository root.

## MDL Classification

```powershell
uv run mdl-classify
```

Defaults:

- input data: `data/current_test_env/data`
- output CSV files: `output/current_test_env`
- packaged prompt: `src/mdl_service/prompts/ccpp_document_classification_prompt_260423.md`

## MDL Ingestion

```powershell
uv run mdl-ingest
```

Defaults:

- input classified CSV files: `output/current_test_env`
- target Neo4j label/index names come from `MDLIngestConfig`

## ITB Extraction

```powershell
uv run itb-extract --section 7
```

Defaults:

- input chunks: `data/current_test_env/data/itb_chunks/R&N_ITB_chunks.json`
- output CSV/JSON/token/rejected files: `output/current_test_env/itb_extract`
- token files are section-specific, e.g. `itb_extraction_section7_tokens.csv`
- packaged prompts: `src/itb_service/prompts/`

## ITB To MDL Matching

```powershell
uv run itb-match
```

Defaults:

- input extraction CSV files: `output/current_test_env/itb_extract/itb_extraction_section*.csv`
- global output matching CSV/JSON files: `output/current_test_env/matching/<retrieval-mode>`
- project-scoped output matching CSV/JSON files: `output/current_test_env/matching/<source-file-stem>/<retrieval-mode>`
- retrieval mode: `keyword`, `semantic`, or `hybrid`
- keyword mode merges aggregated depth and keyword full-text searches
- semantic mode embeds one comma-separated depth-and-keyword query per ITB chunk
- hybrid mode merges keyword and semantic rankings with reciprocal rank fusion
- by default, all matching modes search every MDL document available in Neo4j
- pass `--source-file <MDL workbook name>` to restrict matching to one project/source file
- all modes preserve detected abbreviations and append canonical expansions from `src/common/normalization_rules/abbreviations.json`
- retrieved MDL candidates passed to the cross-encoder: `100`
- final cross-encoder matches written per ITB chunk: `20`

Examples:

```powershell
uv run itb-match --retrieval-mode keyword
uv run itb-match --retrieval-mode semantic
uv run itb-match --retrieval-mode hybrid
uv run itb-match --retrieval-mode hybrid --source-file R&N_MDL.xlsx
```

The default commands search all MDL documents in Neo4j. The `--source-file` example searches only MDL rows whose
Neo4j `source_file` is `R&N_MDL.xlsx` and writes under `output/current_test_env/matching/R_N_MDL/hybrid`.

Use `--help` on any command to see path and runtime overrides.

## ITB To MDL Ground Truth

Generate resumable LLM-assisted ground truth with full LLM verification:

```powershell
uv run itb-eval-build-ground-truth
```

Defaults:

- input matching JSON files: `output/current_test_env/matching/<retrieval-mode>`
- pooled candidates per mode and ITB chunk: `20`
- output ground-truth files: `output/current_test_env/evaluation/ground_truth`
- canonical ground truth updated after verification: `output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth_final.csv`
- resume state: `output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth_resume_state.json`
- LLM judge payloads do not expose retrieval mode, rank, or score
- positive-only judging is enabled by default; the judge selects direct positive MDL matches instead of scoring every candidate
- verification runs only for selected positive judgments and groups them by ITB chunk
- verified positives are merged into the final ground-truth file by default; intermediate CSV files are not written by the CLI
- the verified final file is used directly for evaluation; there is no separate audit step

For the current R&N-only benchmark:

```powershell
uv run itb-match --retrieval-mode hybrid --source-file R&N_MDL.xlsx
uv run itb-eval-build-ground-truth --sections 6 7 --modes hybrid --matching-dir output/current_test_env/matching/R_N_MDL --resume
```

## ITB To MDL Matching Evaluation

Evaluate matching quality against the generated ground truth:

```powershell
uv run itb-eval-matching
```

Defaults:

- input matching JSON files: `output/current_test_env/matching/<retrieval-mode>`
- input ground truth: `output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth_final.csv`
- output reports: `output/current_test_env/evaluation/matching`
- retrieval stage metric: `recall_at_100`
- cross-encoder stage metrics: `recall_at_20` and `hit_rate_at_20`
- recall uses `relevance_threshold=3`, recorded once in `report.json`

---

## Schedule Generation

Start the API server, then POST to `/schedule/generate`:

```bash
source .venv/bin/activate
PYTHONPATH=src uvicorn api.main:app --reload --port 8000

# From MDL candidates CSV (output of /schedule/candidates):
curl -X POST "http://localhost:8000/schedule/generate" --get \
  --data-urlencode "input_csv=output/schedule_service/candidates/mdl_candidates_output_match_all_projects_section6.csv" \
  --data-urlencode "ntp_date=2024-03-01"

# From historical MDL directly:
curl -X POST "http://localhost:8000/schedule/generate" --get \
  --data-urlencode "input_csv=output/schedule_service/classified/Fadhili_MDL_classified.csv" \
  --data-urlencode "ntp_date=2024-03-01" \
  --data-urlencode "activity_resolver=hybrid"
```

`activity_resolver` options: `text` (default), `structured`, `hybrid`.
Requires Azure credentials — loaded from `.env` automatically.

Output files written to `output/schedule_service/generate/`.

## Schedule Benchmark and Diff

```bash
# Benchmark a single run (generates charts + summary):
uv run python scripts/review_schedule_json_metrics.py \
  output/schedule_service/generate/generated_schedule_Fadhili_MDL_classified_ntp2024-03-01.json \
  --out-dir output/schedule_service/bench_text

# Diff two runs (gained/lost usable rows):
uv run python scripts/diff_schedule_runs.py \
  output/schedule_service/generate/generated_schedule_Fadhili_MDL_classified_ntp2024-03-01.json \
  output/schedule_service/generate/generated_schedule_Fadhili_MDL_classified_ntp2024-03-01_resolver-hybrid.json \
  --out-dir output/schedule_service/diff_hybrid_vs_text
```

Bench output: `review_report.md` + PNG charts + summary CSVs.
Diff output: `diff_report.md` + `gained_usable.csv` + `regressions_lost_usable.csv`.

## Tests and Lint

```bash
source .venv/bin/activate
PYTHONPATH=src python -m pytest src/schedule_service/tests/ -q   # 139 tests
ruff check src/
```
