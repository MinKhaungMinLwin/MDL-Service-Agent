<!-- html -->

<header class="page-header">
        <h1>Service Modules</h1>
        <p>Main Python modules under <code>src/</code> and their roles.</p>
      </header>

      <section>
        <table>
          <thead>
            <tr><th>Module</th><th>Path</th><th>Role</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>api</strong></td>
              <td><code>src/api/</code></td>
              <td>FastAPI entry point. Provides health, parser, chunker, and schedule routes</td>
            </tr>
            <tr>
              <td><strong>mdl_service</strong></td>
              <td><code>src/mdl_service/</code></td>
              <td>MDL Excel LLM classification (mdl-classify), Neo4j ingestion (mdl-ingest)</td>
            </tr>
            <tr>
              <td><strong>itb_service</strong></td>
              <td><code>src/itb_service/</code></td>
              <td>LLM extraction of Depth/Keywords/Search Query from ITB chunks (itb-extract)</td>
            </tr>
            <tr>
              <td><strong>matching_service</strong></td>
              <td><code>src/matching_service/</code></td>
              <td>ITB↔MDL vector search + Cross-encoder reranking (itb-match). keyword/semantic/hybrid modes</td>
            </tr>
            <tr>
              <td><strong>schedule_service</strong></td>
              <td><code>src/schedule_service/</code></td>
              <td>MDL candidate extraction (candidates) + FA/FC schedule generation (generate). Core Rule/Activity matching</td>
            </tr>
            <tr>
              <td><strong>evaluation_service</strong></td>
              <td><code>src/evaluation_service/</code></td>
              <td>Matching and schedule quality evaluation, Ground Truth generation, ACC experiments</td>
            </tr>
            <tr>
              <td><strong>parser_service</strong></td>
              <td><code>src/parser_service/</code></td>
              <td>PDF parsing (Docling-based)</td>
            </tr>
            <tr>
              <td><strong>chunker_service</strong></td>
              <td><code>src/chunker_service/</code></td>
              <td>Split parsed documents into hierarchical chunks</td>
            </tr>
            <tr>
              <td><strong>common</strong></td>
              <td><code>src/common/</code></td>
              <td>Neo4j client, OpenAI/Embedding clients, config, text normalization shared utilities</td>
            </tr>
          </tbody>
        </table>
      </section>
