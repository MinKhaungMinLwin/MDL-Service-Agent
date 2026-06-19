<!-- html -->

<header class="page-header">
        <h1>Project Overview</h1>
        <p>A system that automatically generates MDL (Master Document List) for CCPP EPC projects.</p>
        <div class="meta-row">
          <span class="meta-pill"><strong>Version</strong> 0.1.0</span>
          <span class="meta-pill"><strong>Language</strong> Python 3.11+</span>
          <span class="meta-pill"><strong>Branch</strong> phase2-initial</span>
          <span class="meta-pill"><strong>Package</strong> uv</span>
          <span class="meta-pill"><strong>API</strong> FastAPI :8000</span>
        </div>
      </header>

      <section>
        <p>
          For Doosan Enerbility CCPP (Combined Cycle Power Plant) EPC projects, this system analyzes
          <strong>ITB (Invitation To Bid)</strong> documents provided by the client at bid time,
          matches them against historical project
          <strong>MDL (Master Document List)</strong> records, and automatically generates
          the required technical document list and submission schedule (FA/FC dates).
        </p>
        <div class="card-grid">
          <div class="card">
            <h4>Input 1 — ITB</h4>
            <p>Client PDF. Includes equipment, construction, and commissioning requirements. Does not explicitly state which documents must be submitted.</p>
          </div>
          <div class="card">
            <h4>Input 2 — MDL</h4>
            <p>Excel document lists from past CCPP projects (Fadhili, Grati, Karabatan, etc.). Stored as embeddings in Neo4j.</p>
          </div>
          <div class="card">
            <h4>Input 3 — CCPP Guide Schedule</h4>
            <p>Doosan standard schedule reference data. Contains 4,039 activities. Basis for FA/FC date calculation.</p>
          </div>
          <div class="card">
            <h4>Output</h4>
            <p>Per-document FA (First Approval) / FC (Final Comment) submission schedule as JSON/XLSX. Includes ITB source traceability (itb_sources).</p>
          </div>
        </div>
      </section>

      <section>
        <h2>Core Workflow</h2>
        <div class="pipeline">ITB PDF → Parse/Chunk → LLM Extraction → ITB↔MDL Matching
                                              ↓
                              /schedule/candidates (MDL candidate extraction)
                                              ↓
                              /schedule/generate (FA/FC schedule generation)</div>
      </section>
