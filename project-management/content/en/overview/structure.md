<!-- html -->

<header class="page-header">
        <h1>Folder Structure</h1>
        <p>Main directory layout of the repository.</p>
      </header>

      <section>
        <div class="tree"><span class="dir">doosan-mdl/</span>
├── <span class="dir">src/</span>                    <span class="file"># Core Python source</span>
│   ├── <span class="dir">api/</span>                <span class="file"># FastAPI routes</span>
│   ├── <span class="dir">mdl_service/</span>        <span class="file"># MDL classification & ingestion</span>
│   ├── <span class="dir">itb_service/</span>        <span class="file"># ITB extraction</span>
│   ├── <span class="dir">matching_service/</span>   <span class="file"># ITB↔MDL matching</span>
│   ├── <span class="dir">schedule_service/</span>   <span class="file"># Schedule generation (core)</span>
│   ├── <span class="dir">evaluation_service/</span> <span class="file"># Evaluation & Ground Truth</span>
│   ├── <span class="dir">parser_service/</span>     <span class="file"># PDF parsing</span>
│   ├── <span class="dir">chunker_service/</span>    <span class="file"># Document chunking</span>
│   └── <span class="dir">common/</span>             <span class="file"># Shared utilities</span>
├── <span class="dir">data/</span>                   <span class="file"># Input data</span>
│   ├── <span class="dir">current_test_env/</span>   <span class="file"># Test ITB/MDL sources</span>
│   ├── <span class="dir">schedule_service/</span>   <span class="file"># CCPP schedule & Validation Rule</span>
│   └── <span class="dir">sample_documents/</span>
├── <span class="dir">output/</span>                 <span class="file"># Pipeline execution results</span>
│   ├── <span class="dir">current_test_env/</span>   <span class="file"># Matching & classification results</span>
│   └── <span class="dir">schedule_service/</span>   <span class="file"># candidates / generate / cache</span>
├── <span class="dir">docs/</span>                   <span class="file"># Detailed technical docs</span>
├── <span class="dir">references/</span>             <span class="file"># Proposals, vendor docs, system notes</span>
├── <span class="dir">scripts/</span>                <span class="file"># Analysis & utility scripts</span>
├── <span class="dir">tests/</span>                  <span class="file"># Tests</span>
├── <span class="dir">project-management/</span>     <span class="file"># PM dashboard (Next.js)</span>
│   ├── <span class="dir">overview/</span>           <span class="file"># Overview section</span>
│   ├── <span class="dir">backlog/</span>            <span class="file"># Backlog (IA)</span>
│   ├── <span class="dir">issues/</span>             <span class="file"># Issues</span>
│   ├── <span class="dir">wbs/</span>                <span class="file"># Progress Status (WBS)</span>
│   └── <span class="dir">assets/</span>             <span class="file"># Shared CSS & JS</span>
├── <span class="file">pyproject.toml</span>
├── <span class="file">docker-compose.yml</span>
├── <span class="file">Dockerfile</span>
└── <span class="file">CLAUDE.md</span>               <span class="file"># AI agent guide</span></div>
      </section>

      <section>
        <h2>Key Directory Descriptions</h2>
        <table>
          <thead>
            <tr><th>Folder</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>src/</code></td><td>All Python service source code</td></tr>
            <tr><td><code>data/</code></td><td>Input source data (ITB, MDL, CCPP schedule, etc.)</td></tr>
            <tr><td><code>output/</code></td><td>CLI/API execution artifacts (CSV, JSON, XLSX)</td></tr>
            <tr><td><code>docs/</code></td><td>Detailed technical docs such as architecture.md, workflows.md</td></tr>
            <tr><td><code>references/</code></td><td>Proposals, vendor docs, system notes, prompt feedback</td></tr>
            <tr><td><code>scripts/</code></td><td>Utility scripts for Neo4j migration, schedule comparison, etc.</td></tr>
            <tr><td><code>00_current_work/</code></td><td>Current work-in-progress test environment</td></tr>
          </tbody>
        </table>
      </section>
