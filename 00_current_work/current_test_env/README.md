# Current Test Environment

This folder contains standalone wrappers and local artifacts for the MDL/ITB matching services under `src/`.

## Runtime Modules

The wrappers use the shared runtime modules under `src/common/`:

- `common.config`: loads the repository root `.env` and environment variables.
- `common.neo4j_client`: Neo4j driver/session wrapper.
- `common.embedding_client`: Azure OpenAI embedding client.

## Main Flow

1. `classify_mdl_v5-2.py`
   - Reads MDL Excel files from `data/`.
   - Uses `ccpp_document_classification_prompt_260423.md`.
   - Writes `output/*_MDL_classified.csv` with Equipment, Building, System, Study/Survey, Others, and Deliverable classifications.

2. `save_to_neo4j_test.py`
   - Reads classified MDL CSV files from `output/`.
   - Embeds title/classification text.
   - Writes `TestMDLDocument` nodes to Neo4j.
   - Creates the Neo4j full-text and vector indexes.

3. `test_itb_extraction.py`
   - Reads parsed ITB chunk JSON files from `data/itb_chunks/`.
   - Uses `prompts/itb_keyword_extraction_v2.md`.
   - Writes ITB hierarchy, keyword, and LLM-generated search query CSV files under `output/`.

4. `match_itb_advanced.py`
   - Retrieves MDL candidates from ITB depth values.
   - Supports `keyword`, `semantic`, and `hybrid` retrieval through `ITB_RETRIEVAL_MODE`.
   - Uses cross-encoder reranking and writes the top 100 candidates.
   - Writes matched MDL candidates under `output/`.

## Setup

```powershell
# Run from the repository root.
Copy-Item 00_current_work/current_test_env/.env.example .env
uv sync
```

Then fill in `AZURE_OPENAI_API_KEY`, `NEO4J_PASSWORD`, and any non-default endpoint/database values.
