<!-- html -->

<header class="page-header">
        <h1>Tech Stack</h1>
        <p>Main technologies and libraries used in this project.</p>
      </header>

      <section>
        <div class="card-grid">
          <div class="card">
            <h4>Backend</h4>
            <p>Python 3.11, FastAPI, Uvicorn, Pydantic, Pandas</p>
          </div>
          <div class="card">
            <h4>AI / LLM</h4>
            <p>Azure OpenAI (GPT-5.2), text-embedding-3-large, DSPy, Sentence Transformers</p>
          </div>
          <div class="card">
            <h4>Document Processing</h4>
            <p>Docling (PDF parsing), openpyxl (Excel), pypdf</p>
          </div>
          <div class="card">
            <h4>Database</h4>
            <p>Neo4j 5 (HNSW vector index, graph storage)</p>
          </div>
          <div class="card">
            <h4>Search</h4>
            <p>BM25 + Semantic Embedding + RRF (Reciprocal Rank Fusion)</p>
          </div>
          <div class="card">
            <h4>Infrastructure</h4>
            <p>Docker Compose (Neo4j + API), uv package management, Ruff linter</p>
          </div>
        </div>
      </section>

      <section>
        <h2>Key Python Dependencies</h2>
        <table>
          <thead>
            <tr><th>Package</th><th>Purpose</th></tr>
          </thead>
          <tbody>
            <tr><td><code>fastapi</code></td><td>REST API framework</td></tr>
            <tr><td><code>docling</code></td><td>PDF document parsing</td></tr>
            <tr><td><code>dspy</code></td><td>LLM prompt optimization</td></tr>
            <tr><td><code>neo4j</code></td><td>Graph DB + vector search</td></tr>
            <tr><td><code>openai</code></td><td>Azure OpenAI client</td></tr>
            <tr><td><code>sentence-transformers</code></td><td>Cross-encoder reranking</td></tr>
            <tr><td><code>pandas</code></td><td>CSV/data processing</td></tr>
            <tr><td><code>openpyxl</code></td><td>Excel read/write</td></tr>
            <tr><td><code>loguru</code></td><td>Logging</td></tr>
          </tbody>
        </table>
      </section>
