<!-- html -->

<header class="page-header">
        <h1>Full Pipeline</h1>
        <p>Consists of offline preparation steps and a 2-stage runtime API.</p>
      </header>

      <section>
        <h2>Offline Preparation (run once, results saved to disk)</h2>
        <div class="pipeline">[A] CCPP Guide Schedule XLSX
      └─ data_prep/ccpp_schedule_cleaner.py
            └─▶ ccpp_guide_schedule_260527_clean.json  (4,039 activities)

[B] Historical MDL Excel (*_MDL.xlsx)
      └─ uv run mdl-classify  (LLM classification)
            └─▶ *_MDL_classified.csv
                  └─ uv run mdl-ingest
                        └─▶ Neo4j: MDL document nodes + HNSW vector index

[C] ITB PDF
      └─ /parser + /chunker  (API)
            └─▶ ITB chunks JSON
                  └─ uv run itb-extract  (LLM extraction)
                        └─▶ itb_extraction_section*.csv
                              └─ uv run itb-match  (Neo4j vector search)
                                    └─▶ output_match_*.csv</div>
      </section>

      <section>
        <h2>Runtime API (2 stages)</h2>
        <div class="pipeline">output_match_*.csv
        │
        ▼
  POST /schedule/candidates
  (ITB chunks → required MDL document extraction, dedup, optional LLM classification)
        │
        ▼
  mdl_candidates_*.csv
        │
        ▼
  POST /schedule/generate
  (Validation Rule matching + Activity search + NTP date shift + FA/FC calculation)
        │
        ▼
  generated_schedule_*.json / .xlsx</div>
      </section>

      <section>
        <h2>/schedule/generate Internal Processing</h2>
        <p>For each MDL document row, the following 3 steps are performed.</p>
        <table>
          <thead>
            <tr><th>Step</th><th>Processing</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>1. Rule matching</td>
              <td>Deliverable + Equipment → Validation Rule hybrid (token+semantic) matching → FA/FI/SKIP + VT formula</td>
            </tr>
            <tr>
              <td>2. Activity search</td>
              <td>Search activities in CCPP Guide Schedule via BM25 + semantic + RRF → determine anchor_date</td>
            </tr>
            <tr>
              <td>3. Date calculation</td>
              <td>Compute FA range via VT formula, FC = FA + 60 days (or FC formula). Shift to real calendar when NTP date provided</td>
            </tr>
          </tbody>
        </table>
      </section>
