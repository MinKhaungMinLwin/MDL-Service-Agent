# Repository Guidelines

## Project Structure & Module Organization

This repository is organized as an MDL/ITB matching workspace. Active runnable code is in `00_current_work/current_test_env/`, including workflow scripts such as `classify_mdl_v5-2.py`, `save_to_neo4j_test.py`, `test_itb_extraction.py`, and `match_itb_advanced.py`. Shared runtime helpers for configuration, Neo4j, and embeddings live in `00_current_work/current_test_env/mdl_runtime/`.

Top-level `src/` currently contains package metadata and generated caches; do not treat cached files as source. Reference material belongs in `03_reference_docs/`, source/sample documents in `04_data/`, and generated CSV/results in `output/` or `00_current_work/current_test_env/output/`.

## Build, Test, and Development Commands

Run commands from `00_current_work/current_test_env/` unless noted, because scripts rely on relative prompt, data, and output paths.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install the standalone test environment dependencies. If `uv` is available, `uv pip install -r requirements.txt` is also acceptable.

```bash
python classify_mdl_v5-2.py
python save_to_neo4j_test.py
python test_itb_extraction.py
python match_itb_advanced.py
```

Run the main classification, Neo4j ingestion, ITB extraction, and matching steps. These commands require configured API and database credentials.

## Coding Style & Naming Conventions

Use Python 3.11+. Follow PEP 8 with 4-space indentation, descriptive snake_case function and variable names, and PascalCase only for classes. Keep scripts focused on one pipeline step and place reusable logic in `mdl_runtime/` instead of duplicating client or config code. Prefer `pathlib`, typed Pydantic models where useful, and explicit environment-variable names.

## Testing Guidelines

Current tests are script-style checks, named with `test_*.py`, such as `test_vector_filter.py` and `test_itb_extraction.py`. Run them directly from `00_current_work/current_test_env/` after installing dependencies. For new tests, avoid relying on live Azure OpenAI or Neo4j unless the test is explicitly an integration check; isolate pure parsing, filtering, and ranking logic where possible.

## Commit & Pull Request Guidelines

Existing history uses concise subjects such as `feat: update match logic and prompts for ITB keyword extraction & matching`. Use imperative, scoped messages with a conventional prefix when helpful: `feat:`, `fix:`, `docs:`, or `test:`.

Pull requests should include the workflow affected, commands run, key output files changed, and any credential or data assumptions. Include screenshots or CSV excerpts only when they clarify changed matching/classification behavior. Do not commit `.env`, `.venv/`, `__pycache__/`, or generated bulk data unless explicitly required.

## Security & Configuration Tips

Copy `.env.example` to `.env` locally and fill in `AZURE_OPENAI_API_KEY`, `NEO4J_PASSWORD`, and endpoint/database settings. Keep secrets and customer documents out of commits; use the existing ignored local paths for runtime artifacts.

## Local Work History

Maintain the session work log at `.codex/FIX_LOG.md`. The `.codex/` directory is ignored by Git, so this file is for local handoff/history only and should not be committed.

Whenever code, prompt, workflow, output, validation, or execution behavior changes during a session, append a concise entry to `.codex/FIX_LOG.md` with:

- Date and short purpose of the change
- Files, scripts, prompts, and output paths affected
- Commands run and important parameters
- Validation results or known limitations
- Any follow-up work or review points
