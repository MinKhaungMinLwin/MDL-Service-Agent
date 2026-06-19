<!-- html -->

<header class="page-header">
        <h1>폴더 구조</h1>
        <p>저장소의 주요 디렉터리 구성입니다.</p>
      </header>

      <section>
        <div class="tree"><span class="dir">doosan-mdl/</span>
├── <span class="dir">src/</span>                    <span class="file"># 핵심 Python 소스</span>
│   ├── <span class="dir">api/</span>                <span class="file"># FastAPI 라우트</span>
│   ├── <span class="dir">mdl_service/</span>        <span class="file"># MDL 분류·적재</span>
│   ├── <span class="dir">itb_service/</span>        <span class="file"># ITB 추출</span>
│   ├── <span class="dir">matching_service/</span>   <span class="file"># ITB↔MDL 매칭</span>
│   ├── <span class="dir">schedule_service/</span>   <span class="file"># 일정 생성 (핵심)</span>
│   ├── <span class="dir">evaluation_service/</span> <span class="file"># 평가·Ground Truth</span>
│   ├── <span class="dir">parser_service/</span>     <span class="file"># PDF 파싱</span>
│   ├── <span class="dir">chunker_service/</span>    <span class="file"># 문서 청킹</span>
│   └── <span class="dir">common/</span>             <span class="file"># 공통 유틸</span>
├── <span class="dir">data/</span>                   <span class="file"># 입력 데이터</span>
│   ├── <span class="dir">current_test_env/</span>   <span class="file"># 테스트용 ITB/MDL 원본</span>
│   ├── <span class="dir">schedule_service/</span>   <span class="file"># CCPP 일정·Validation Rule</span>
│   └── <span class="dir">sample_documents/</span>
├── <span class="dir">output/</span>                 <span class="file"># 파이프라인 실행 결과</span>
│   ├── <span class="dir">current_test_env/</span>   <span class="file"># 매칭·분류 결과</span>
│   └── <span class="dir">schedule_service/</span>   <span class="file"># candidates / generate / cache</span>
├── <span class="dir">docs/</span>                   <span class="file"># 상세 기술 문서</span>
├── <span class="dir">references/</span>             <span class="file"># 제안서, 벤더 문서, 시스템 노트</span>
├── <span class="dir">scripts/</span>                <span class="file"># 분석·유틸 스크립트</span>
├── <span class="dir">tests/</span>                  <span class="file"># 테스트</span>
├── <span class="dir">project-management/</span>     <span class="file"># PM 대시보드 (Next.js)</span>
│   ├── <span class="dir">overview/</span>           <span class="file"># Overview 섹션</span>
│   ├── <span class="dir">backlog/</span>            <span class="file"># Backlog (IA)</span>
│   ├── <span class="dir">issues/</span>             <span class="file"># Issues</span>
│   ├── <span class="dir">wbs/</span>                <span class="file"># 진행현황 (WBS)</span>
│   └── <span class="dir">assets/</span>             <span class="file"># 공통 CSS·JS</span>
├── <span class="file">pyproject.toml</span>
├── <span class="file">docker-compose.yml</span>
├── <span class="file">Dockerfile</span>
└── <span class="file">CLAUDE.md</span>               <span class="file"># AI 에이전트용 가이드</span></div>
      </section>

      <section>
        <h2>주요 디렉터리 설명</h2>
        <table>
          <thead>
            <tr><th>폴더</th><th>설명</th></tr>
          </thead>
          <tbody>
            <tr><td><code>src/</code></td><td>모든 Python 서비스 소스 코드</td></tr>
            <tr><td><code>data/</code></td><td>입력 원본 데이터 (ITB, MDL, CCPP 일정 등)</td></tr>
            <tr><td><code>output/</code></td><td>CLI/API 실행 결과물 (CSV, JSON, XLSX)</td></tr>
            <tr><td><code>docs/</code></td><td>architecture.md, workflows.md 등 상세 기술 문서</td></tr>
            <tr><td><code>references/</code></td><td>제안서, 벤더 문서, 시스템 노트, 프롬프트 피드백</td></tr>
            <tr><td><code>scripts/</code></td><td>Neo4j 마이그레이션, 일정 비교 등 유틸 스크립트</td></tr>
            <tr><td><code>00_current_work/</code></td><td>현재 작업 중인 테스트 환경</td></tr>
          </tbody>
        </table>
      </section>
