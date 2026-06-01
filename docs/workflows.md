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
- depth retrieval mode: `keyword`, `semantic`, or `hybrid`
- retrieved MDL candidates passed to the cross-encoder: `500`
- final cross-encoder matches written per ITB chunk: `100`

Examples:

```powershell
uv run itb-match --retrieval-mode keyword
uv run itb-match --retrieval-mode semantic
uv run itb-match --retrieval-mode hybrid
```

Use `--help` on any command to see path and runtime overrides.
