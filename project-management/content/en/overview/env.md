<!-- html -->

<header class="page-header">
        <h1>Environment Variables</h1>
        <p>Copy <code>.env.example</code> to <code>.env</code> and fill in the values.</p>
      </header>

      <section>
        <h2>Azure OpenAI</h2>
        <table>
          <thead>
            <tr><th>Variable</th><th>Description</th><th>Example</th></tr>
          </thead>
          <tbody>
            <tr><td><code>AZURE_OPENAI_ENDPOINT</code></td><td>Azure OpenAI endpoint</td><td><code>https://....openai.azure.com/</code></td></tr>
            <tr><td><code>AZURE_OPENAI_API_KEY</code></td><td>API key</td><td>—</td></tr>
            <tr><td><code>AZURE_OPENAI_CHAT_DEPLOYMENT</code></td><td>Chat model deployment name</td><td><code>gpt-5.2</code></td></tr>
            <tr><td><code>AZURE_OPENAI_CHAT_API_VERSION</code></td><td>Chat API version</td><td><code>2024-12-01-preview</code></td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Embedding</h2>
        <table>
          <thead>
            <tr><th>Variable</th><th>Description</th><th>Example</th></tr>
          </thead>
          <tbody>
            <tr><td><code>EMBEDDING_MODEL</code></td><td>Embedding model</td><td><code>text-embedding-3-large</code></td></tr>
            <tr><td><code>EMBEDDING_DIMENSIONS</code></td><td>Embedding dimensions</td><td><code>1536</code></td></tr>
            <tr><td><code>EMBEDDING_BATCH_SIZE</code></td><td>Batch size</td><td><code>2048</code></td></tr>
            <tr><td><code>AZURE_OPENAI_EMBEDDING_API_VERSION</code></td><td>Embedding API version</td><td><code>2024-02-01</code></td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Neo4j</h2>
        <table>
          <thead>
            <tr><th>Variable</th><th>Description</th><th>Example</th></tr>
          </thead>
          <tbody>
            <tr><td><code>NEO4J_URI</code></td><td>Connection URI</td><td><code>bolt://localhost:7687</code></td></tr>
            <tr><td><code>NEO4J_USER</code></td><td>User</td><td><code>neo4j</code></td></tr>
            <tr><td><code>NEO4J_PASSWORD</code></td><td>Password</td><td>—</td></tr>
            <tr><td><code>NEO4J_DATABASE</code></td><td>Database</td><td><code>neo4j</code></td></tr>
            <tr><td><code>NEO4J_MAX_POOL_SIZE</code></td><td>Connection pool size</td><td><code>50</code></td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Setup</h2>
        <pre>cp .env.example .env
# Open .env and enter API keys, Neo4j password, etc.</pre>
        <div class="alert alert-warn">
          <code>/schedule/generate</code> requires semantic matching, so Azure OpenAI credentials are mandatory.
        </div>
      </section>
