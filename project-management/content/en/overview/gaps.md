<!-- html -->

<header class="page-header">
        <h1>Known Limitations</h1>
        <p>Unimplemented items and current constraints of the system.</p>
      </header>

      <section>
        <table>
          <thead>
            <tr><th>Item</th><th>Details</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>NTP date shift</strong></td>
              <td><code>ntp_date</code> linearly shifts template dates (anchored at 2007-03-01). Actual PO date mapping is not implemented. <code>ScheduleActivity.po_finish_date</code> is always empty.</td>
            </tr>
            <tr>
              <td><strong>CLI-first workflow</strong></td>
              <td>ITB extraction and MDL classification run via CLI (<code>itb-extract</code>, <code>mdl-classify</code>, etc.). API exposes parser/chunker/schedule only.</td>
            </tr>
            <tr>
              <td><strong>No LLM Activity selection</strong></td>
              <td>Legacy <code>/schedule/map</code> removed. Activities are auto-selected via BM25+semantic+RRF.</td>
            </tr>
            <tr>
              <td><strong>No final MDL Excel format</strong></td>
              <td>Output is an internal table format. Client deliverable Excel formatter not implemented.</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Resolved Items</h2>
        <div class="card">
          <h4>Semantic index caching</h4>
          <p>Previously re-embedded on every request; now cached via <code>resource_cache</code> + disk cache for improved performance.</p>
        </div>
      </section>
