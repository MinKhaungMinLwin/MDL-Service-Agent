<!-- html -->

<header class="page-header">
        <h1>How to Run</h1>
        <p>Local development setup and pipeline execution guide.</p>
      </header>

      <section>
        <h2>Initial Setup</h2>
        <pre>cp .env.example .env   # fill in values
uv sync
source .venv/bin/activate
docker compose up neo4j -d</pre>
      </section>

      <section>
        <h2>Run API Server</h2>
        <pre>PYTHONPATH=src uvicorn api.main:app --reload --port 8000</pre>
        <p>Health check: <code>http://localhost:8000/health</code></p>
      </section>

      <section>
        <h2>Docker Compose (API + Neo4j)</h2>
        <pre>docker compose up -d</pre>
      </section>

      <section>
        <h2>Full Pipeline Example</h2>
        <h3>1. ITB Matching (CLI)</h3>
        <pre>uv run itb-match --retrieval-mode hybrid</pre>

        <h3>2. MDL Candidate Extraction (API)</h3>
        <pre>curl -X POST "http://localhost:8000/schedule/candidates" \
  --get --data-urlencode "input_csv=output/current_test_env/matching/hybrid/output_match_all_projects_section6.csv"</pre>

        <h3>3. FA/FC Schedule Generation (API)</h3>
        <pre>curl -X POST "http://localhost:8000/schedule/generate" \
  --get \
  --data-urlencode "input_csv=output/schedule_service/candidates/mdl_candidates_output_match_all_projects_section6.csv" \
  --data-urlencode "ntp_date=2024-03-01"</pre>

        <h3>Or use historical MDL directly</h3>
        <pre>curl -X POST "http://localhost:8000/schedule/generate" \
  --get --data-urlencode "input_csv=output/current_test_env/Fadhili_MDL_classified.csv" \
  -d "limit=50"</pre>
      </section>

      <section>
        <h2>Lint / Tests</h2>
        <pre>ruff check src/
python -m pytest src/schedule_service/tests/ -v</pre>
      </section>
