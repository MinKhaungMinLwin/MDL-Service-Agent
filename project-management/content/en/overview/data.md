<!-- html -->

<header class="page-header">
        <h1>Key Data Files</h1>
        <p>Core input and output files used in the pipeline.</p>
      </header>

      <section>
        <h2>Input / Reference Data</h2>
        <table>
          <thead>
            <tr><th>File</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><code>data/schedule_service/processed/ccpp_guide_schedule_260527_clean.json</code></td>
              <td>CCPP standard schedule — 4,039 activities (DEFAULT_SCHEDULE_PATH)</td>
            </tr>
            <tr>
              <td><code>data/schedule_service/processed/validation_rule_clean.csv</code></td>
              <td>FA/FI rule table (DEFAULT_RULE_PATH)</td>
            </tr>
            <tr>
              <td><code>data/schedule_service/raw/validation_rule.csv</code></td>
              <td>Raw Validation Rule (pre-processing)</td>
            </tr>
            <tr>
              <td><code>data/current_test_env/data/</code></td>
              <td>Test ITB/MDL source Excel, PDF, and chunks</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Intermediate / Output Data</h2>
        <table>
          <thead>
            <tr><th>File</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><code>output/current_test_env/*_MDL_classified.csv</code></td>
              <td>LLM-classified MDL data</td>
            </tr>
            <tr>
              <td><code>output/current_test_env/matching/*/output_match_*.csv</code></td>
              <td>ITB↔MDL matching results (Matched_Doc_1..20 columns)</td>
            </tr>
            <tr>
              <td><code>output/schedule_service/candidates/mdl_candidates_*.csv</code></td>
              <td>/schedule/candidates API output</td>
            </tr>
            <tr>
              <td><code>output/schedule_service/generate/generated_schedule_*.json</code></td>
              <td>/schedule/generate API output (FA/FC dates)</td>
            </tr>
            <tr>
              <td><code>output/schedule_service/cache/</code></td>
              <td>Semantic index and embedding disk cache</td>
            </tr>
          </tbody>
        </table>
      </section>
