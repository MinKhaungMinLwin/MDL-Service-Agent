<!-- html -->

<header class="page-header">
        <h1>기술 스택</h1>
        <p>프로젝트에서 사용하는 주요 기술과 라이브러리입니다.</p>
      </header>

      <section>
        <div class="card-grid">
          <div class="card">
            <h4>백엔드</h4>
            <p>Python 3.11, FastAPI, Uvicorn, Pydantic, Pandas</p>
          </div>
          <div class="card">
            <h4>AI / LLM</h4>
            <p>Azure OpenAI (GPT-5.2), text-embedding-3-large, DSPy, Sentence Transformers</p>
          </div>
          <div class="card">
            <h4>문서 처리</h4>
            <p>Docling (PDF 파싱), openpyxl (Excel), pypdf</p>
          </div>
          <div class="card">
            <h4>데이터베이스</h4>
            <p>Neo4j 5 (벡터 인덱스 HNSW, 그래프 저장)</p>
          </div>
          <div class="card">
            <h4>검색</h4>
            <p>BM25 + Semantic Embedding + RRF(Reciprocal Rank Fusion)</p>
          </div>
          <div class="card">
            <h4>인프라</h4>
            <p>Docker Compose (Neo4j + API), uv 패키지 관리, Ruff 린터</p>
          </div>
        </div>
      </section>

      <section>
        <h2>주요 Python 의존성</h2>
        <table>
          <thead>
            <tr><th>패키지</th><th>용도</th></tr>
          </thead>
          <tbody>
            <tr><td><code>fastapi</code></td><td>REST API 프레임워크</td></tr>
            <tr><td><code>docling</code></td><td>PDF 문서 파싱</td></tr>
            <tr><td><code>dspy</code></td><td>LLM 프롬프트 최적화</td></tr>
            <tr><td><code>neo4j</code></td><td>그래프 DB + 벡터 검색</td></tr>
            <tr><td><code>openai</code></td><td>Azure OpenAI 클라이언트</td></tr>
            <tr><td><code>sentence-transformers</code></td><td>Cross-encoder 재순위</td></tr>
            <tr><td><code>pandas</code></td><td>CSV/데이터 처리</td></tr>
            <tr><td><code>openpyxl</code></td><td>Excel 읽기/쓰기</td></tr>
            <tr><td><code>loguru</code></td><td>로깅</td></tr>
          </tbody>
        </table>
      </section>
