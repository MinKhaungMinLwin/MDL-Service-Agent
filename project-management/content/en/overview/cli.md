<!-- html -->

<header class="page-header">
        <h1>CLI Commands</h1>
        <p>Run from the repository root with <code>uv run &lt;command&gt;</code>.</p>
      </header>

      <section>
        <h2>MDL / ITB Processing</h2>
        <table>
          <thead>
            <tr><th>Command</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><span class="tag tag-cli">mdl-classify</span></td><td>MDL Excel → LLM classification CSV</td></tr>
            <tr><td><span class="tag tag-cli">mdl-ingest</span></td><td>Classified MDL CSV → Neo4j ingestion</td></tr>
            <tr><td><span class="tag tag-cli">mdl-export-catalog</span></td><td>Export MDL catalog</td></tr>
            <tr><td><span class="tag tag-cli">itb-extract</span></td><td>ITB chunks → Depth/Keywords LLM extraction</td></tr>
            <tr><td><span class="tag tag-cli">itb-match</span></td><td>ITB↔MDL matching (keyword / semantic / hybrid)</td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Evaluation / Experiments</h2>
        <table>
          <thead>
            <tr><th>Command</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><span class="tag tag-cli">itb-eval-build-ground-truth</span></td><td>Build matching Ground Truth (LLM validation)</td></tr>
            <tr><td><span class="tag tag-cli">itb-eval-matching</span></td><td>Evaluate matching quality</td></tr>
            <tr><td><span class="tag tag-cli">schedule-eval</span></td><td>Evaluate schedule generation quality</td></tr>
            <tr><td><span class="tag tag-cli">acc-*</span></td><td>ACC (accuracy) experiment commands</td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Usage Examples</h2>
        <pre>uv run mdl-classify
uv run mdl-ingest
uv run itb-extract --section 7
uv run itb-match --retrieval-mode hybrid
uv run itb-match --retrieval-mode hybrid --source-file R&N_MDL.xlsx</pre>
      </section>
