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
- token files are section-specific, e.g. `output_itb_section7_focused_tokens.csv`
- packaged prompts: `src/itb_service/prompts/`

## ITB To MDL Matching

```powershell
uv run itb-match
```

Defaults:

- input extraction CSV files: `output/current_test_env/itb_extract/output_itb_section*_focused.csv`
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
- verified evaluation input: `output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth_verified.csv`
- LLM judge payloads do not expose retrieval mode, rank, or score
- positive-only judging is enabled by default; the judge selects direct positive MDL matches instead of scoring every candidate
- verification runs only for selected positive judgments by default

For the current R&N-only benchmark:

```powershell
uv run itb-match --retrieval-mode hybrid --source-file R&N_MDL.xlsx
uv run itb-eval-build-ground-truth --sections 6 7 --modes hybrid --matching-dir output/current_test_env/matching/R_N_MDL --resume
```

Use full 0-3 candidate judging only when negative labels are needed:

```powershell
uv run itb-eval-build-ground-truth --full-judgment
```

To skip verification for a quick silver-label run:

```powershell
uv run itb-eval-build-ground-truth --no-verify
```

## ITB To MDL Matching Evaluation

Evaluate matching quality against the generated ground truth:

```powershell
uv run itb-eval-matching
```

Defaults:

- input matching JSON files: `output/current_test_env/matching/<retrieval-mode>`
- input ground truth: `output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth_verified.csv`
- output reports: `output/current_test_env/evaluation/matching`
- retrieval stage metrics: `recall_at_100` and `judged_at_100`
- cross-encoder stage metrics: `recall_at_20` and `judged_at_20`
- recall uses `relevance_threshold=3`, recorded once in `report.json`
