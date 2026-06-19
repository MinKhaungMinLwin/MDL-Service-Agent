<!-- html -->

<header class="page-header">
        <h1>알려진 한계</h1>
        <p>현재 시스템의 미구현 항목과 제한 사항입니다.</p>
      </header>

      <section>
        <table>
          <thead>
            <tr><th>항목</th><th>내용</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>NTP 날짜 이동</strong></td>
              <td><code>ntp_date</code>로 템플릿 날짜(2007-03-01 기준)를 선형 이동. 실제 PO 날짜 매핑은 미구현. <code>ScheduleActivity.po_finish_date</code>는 항상 빈 값.</td>
            </tr>
            <tr>
              <td><strong>CLI 우선 워크플로</strong></td>
              <td>ITB 추출·MDL 분류는 CLI(<code>itb-extract</code>, <code>mdl-classify</code> 등)로 실행. API로는 parser/chunker/schedule만 제공.</td>
            </tr>
            <tr>
              <td><strong>LLM Activity 선택 없음</strong></td>
              <td>구 <code>/schedule/map</code> 제거. Activity는 BM25+semantic+RRF로 자동 선택.</td>
            </tr>
            <tr>
              <td><strong>최종 MDL Excel 포맷 없음</strong></td>
              <td>출력은 내부 테이블 형식. 고객 납품용 Excel 포맷터 미구현.</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>해결된 항목</h2>
        <div class="card">
          <h4>시맨틱 인덱스 캐싱</h4>
          <p>이전에는 요청마다 재임베딩했으나, 현재 <code>resource_cache</code> + 디스크 캐시로 캐싱되어 성능이 개선됨.</p>
        </div>
      </section>
