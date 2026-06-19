<!-- html -->

<header class="page-header">
        <h1>API Endpoints</h1>
        <p>FastAPI-based REST API. Default port <code>8000</code>.</p>
      </header>

      <section>
        <table>
          <thead>
            <tr><th>Method</th><th>Path</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><span class="tag tag-api">GET</span></td>
              <td><code>/health</code></td>
              <td>Service health check</td>
            </tr>
            <tr>
              <td><span class="tag tag-api">POST</span></td>
              <td><code>/parser/...</code></td>
              <td>PDF upload and parsing</td>
            </tr>
            <tr>
              <td><span class="tag tag-api">POST</span></td>
              <td><code>/chunker/...</code></td>
              <td>Split parsed results into chunks</td>
            </tr>
            <tr>
              <td><span class="tag tag-api">POST</span></td>
              <td><code>/schedule/candidates</code></td>
              <td>ITB matching results → MDL document candidate list. Supports <code>classify_with_llm</code> option</td>
            </tr>
            <tr>
              <td><span class="tag tag-api">POST</span></td>
              <td><code>/schedule/generate</code></td>
              <td>MDL documents → FA/FC date generation. <code>ntp_date</code>, <code>rule_csv</code> options. Semantic matching required (Azure credentials needed)</td>
            </tr>
          </tbody>
        </table>

        <div class="alert alert-warn">
          The <code>/schedule/map</code> endpoint was removed in the <code>feat/mia-2</code> refactor.
          Activity lookup is now handled inside <code>/schedule/generate</code>.
        </div>
      </section>

      <section>
        <h2>/schedule/candidates</h2>
        <p>Takes <code>output_match_*.csv</code> as input, parses Matched_Doc_1..N (score ≥ 0.75) per ITB chunk, and generates an MDL candidate list.</p>
        <pre>curl -X POST "http://localhost:8000/schedule/candidates" \
  --get --data-urlencode "input_csv=output/current_test_env/matching/hybrid/output_match_all_projects_section6.csv"</pre>
      </section>

      <section>
        <h2>/schedule/generate</h2>
        <p>Takes <code>mdl_candidates_*.csv</code> or <code>*_MDL_classified.csv</code> as input and generates FA/FC schedules.</p>
        <pre>curl -X POST "http://localhost:8000/schedule/generate" \
  --get \
  --data-urlencode "input_csv=output/schedule_service/candidates/mdl_candidates_....csv" \
  --data-urlencode "ntp_date=2024-03-01"</pre>
      </section>
