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
- output matching CSV/JSON files: `output/current_test_env/matching/<retrieval-mode>`
- retrieval mode: `keyword`, `semantic`, or `hybrid`
- keyword mode merges aggregated depth and keyword full-text searches
- semantic mode embeds one comma-separated depth-and-keyword query per ITB chunk
- hybrid mode merges keyword and semantic rankings with reciprocal rank fusion
- all modes preserve detected abbreviations and append canonical expansions from `src/common/normalization_rules/abbreviations.json`
- retrieved MDL candidates passed to the cross-encoder: `100`
- final cross-encoder matches written per ITB chunk: `20`

Examples:

```powershell
uv run itb-match --retrieval-mode keyword
uv run itb-match --retrieval-mode semantic
uv run itb-match --retrieval-mode hybrid
```

Use `--help` on any command to see path and runtime overrides.

## ITB To MDL Ground Truth

Build a blind candidate pool from the top matching results for sections 6 and 7:

```powershell
uv run itb-eval-build-ground-truth --pool-only
```

Generate resumable LLM-assisted silver ground truth with full LLM verification:

```powershell
uv run itb-eval-build-ground-truth --verify
```

Defaults:

- input matching JSON files: `output/current_test_env/matching/<retrieval-mode>`
- pooled candidates per mode and ITB chunk: `20`
- output ground-truth files: `output/current_test_env/evaluation/ground_truth`
- LLM judge payloads do not expose retrieval mode, rank, or score
- verification runs for every LLM judgment

## ITB To MDL Matching Evaluation

Evaluate matching quality against the generated ground truth:

```powershell
uv run itb-eval-matching
```

Defaults:

- input matching JSON files: `output/current_test_env/matching/<retrieval-mode>`
- input ground truth: `output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth.csv`
- output reports: `output/current_test_env/evaluation/matching`
- retrieval stage metrics: strong-relevance recall and judgment coverage at `100`
- cross-encoder stage metrics: graded `nDCG@10`, strong-relevance recall at `20`, precision and success at `5`
