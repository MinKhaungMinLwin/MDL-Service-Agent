# Current Test Environment

This folder is a standalone MDL/ITB matching test environment. It no longer imports modules from the legacy `master-document-list-project-main/backend` project.

## Runtime Modules

The local `mdl_runtime/` package replaces the small subset of legacy backend code that these scripts used:

- `mdl_runtime.config`: loads `.env`, `.env.local`, and environment variables.
- `mdl_runtime.neo4j_connection`: Neo4j driver/session wrapper.
- `mdl_runtime.embeddings`: Azure OpenAI embedding client with the same `UnifiedEmbeddingService.build_default()` API used by the old scripts.

## Main Flow

1. `classify_mdl_v5-2.py`
   - Reads MDL Excel files from `data/`.
   - Uses `ccpp_document_classification_prompt_260423.md`.
   - Writes `output/*_MDL_classified.csv` with Equipment, Building, System, Study/Survey, Others, and Deliverable classifications.

2. `save_to_neo4j_test.py`
   - Reads classified MDL CSV files from `output/`.
   - Embeds title/classification text.
   - Writes `TestMDLDocument` nodes to Neo4j.
   - Creates `test_mdl_document_vector_idx`.

3. `test_itb_extraction.py`
   - Reads parsed ITB chunk JSON files from `data/itb_chunks/`.
   - Uses `itb_keyword_extraction_prompt.md`.
   - Writes ITB hierarchy, keyword, and LLM-generated search query CSV files under `output/`.

4. `match_itb_fadhili_only.py` or `match_itb_advanced.py`
   - Embeds the ITB `Search Query` column when available; otherwise falls back to meaningful Depth + Keyword queries.
   - Searches the Neo4j vector index.
   - Writes matched MDL candidates under `output/`.

## Setup

```powershell
# 1. 환경변수 파일 복사 (필수 인증키 기입 필요)
Copy-Item .env.example .env

# 2. 파이썬 가상환경 생성 및 활성화 (Windows)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. 패키지 설치
# (uv가 설치되어 있다면 'uv pip install -r requirements.txt' 권장)
pip install -r requirements.txt
```

Then fill in `AZURE_OPENAI_API_KEY`, `NEO4J_PASSWORD`, and any non-default endpoint/database values.

Run scripts from this directory so relative prompt/data paths stay predictable.
