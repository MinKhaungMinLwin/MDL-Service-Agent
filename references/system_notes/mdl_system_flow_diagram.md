# Master Document List 시스템 전체 흐름도

## 1. 전체 파이프라인 개요

```mermaid
flowchart TB
    subgraph INPUT["🔵 사용자 입력"]
        ITB["📄 신규 ITB PDF"]
        L3["📊 Level 3 Schedule Excel"]
        REF["🏭 참조 플랜트 지정"]
    end

    subgraph DL["🟣 학습용 Data Layer (사전 구축)"]
        direction TB
        P1["Pipeline 1: 이력 ITB 인덱싱"]
        P2["Pipeline 2: 참조 MDL 인덱싱"]
        P3["학습 데이터 전처리"]
        NEO4J[("Neo4j\nGraph DB")]
        MILVUS[("Milvus\nVector DB")]
        P1 --> NEO4J
        P2 --> NEO4J
        P3 --> MILVUS
    end

    subgraph STAGE3["🟢 3단계: MDL 도서명 생성"]
        S31["3-1. ITB 및 기준 MDL 업로드"]
        S32["3-2. ITB Chunking + LLM 엔티티 추출"]
        S33["3-3. 이름 기반 Work Component 1차 매칭"]
        S34["3-4. 3-Tier Vector 기반 도서명 2차 생성"]
        S31 --> S32 --> S33 --> S34
    end

    subgraph STAGE4["🟠 4단계: MDL 일정 생성"]
        S41["4-1. L3 전처리 및 NTP 추출"]
        S42["4-2. Hybrid Search 유사 도서 탐색"]
        S43["4-3. 가중평균 기반 FA/FC 일정 예측"]
        S41 --> S42 --> S43
    end

    subgraph STAGE5["🔴 5단계: MDL - L3 일정 비교"]
        S51["5-1. Semantic Search 기반 1차 매칭"]
        S52["5-2. System Code 기반 2차 매칭"]
        S53["5-3. Over/Under Validation"]
        S54["5-4. 사용자 피드백 (OK / Not OK)"]
        S51 --> S52 --> S53 --> S54
    end

    ITB --> S31
    REF --> S31
    L3 --> S41
    DL -.->|참조| STAGE3
    DL -.->|참조| STAGE4
    DL -.->|참조| STAGE5
    S34 -->|"Pre-MDL\n(도서명 목록)"| S41
    S43 -->|"일정 포함 MDL"| S51
    S54 -->|"최종 MDL Report"| OUTPUT["📋 최종 산출물\n(Excel 다운로드)"]
```

---

## 2. 학습용 Data Layer 구축 흐름

```mermaid
flowchart LR
    subgraph IN1["입력"]
        HITB["과거 ITB PDF"]
        HMDL["과거 MDL Excel"]
        HL3["과거 L3 Schedule"]
    end

    subgraph PIPE1["Pipeline 1\n이력 ITB 인덱싱"]
        D1["Docling 파싱"]
        C1["Chunking\n60~600 토큰"]
        NER1["LLM NER 추출\nWork Component\nDeliverable\nStandard"]
        D1 --> C1 --> NER1
    end

    subgraph PIPE2["Pipeline 2\n참조 MDL 인덱싱"]
        P2A["도서명 파싱\nWork Component\n+ Deliverable 분리"]
        P2B["LLM 엔티티 추출"]
        P2C["NPMI\nConfidence 산출"]
        P2D["임베딩 벡터 생성\ntext-embedding-3-large\n1536차원"]
        P2A --> P2B --> P2C --> P2D
    end

    subgraph PIPE3["학습 데이터 전처리"]
        P3A["MDL+L3 쌍 전처리\nNTP 기준 일수 계산"]
        P3B["임베딩 생성 +\nBM25 인덱스 학습"]
        P3C["LightGBM\n모델 학습"]
        P3A --> P3B --> P3C
    end

    HITB --> PIPE1
    HMDL --> PIPE2
    HMDL --> PIPE3
    HL3 --> PIPE3

    PIPE1 -->|"ITBWorkComponent\nITBChunk 노드"| NEO[("Neo4j")]
    PIPE2 -->|"WorkComponent\nDeliverableRequirement\nHNSW Vector Index"| NEO
    PIPE3 -->|"학습 데이터프레임\nBM25 모델"| MIL[("Milvus +\n파일 시스템")]
```

---

## 3. MDL 도서명 생성 상세 흐름 (3단계)

```mermaid
flowchart TB
    ITB_UP["📄 신규 ITB PDF 업로드"] --> PARSE["Docling PDF 파싱\n레이아웃 인식"]
    PARSE --> CHUNK["HybridChunker 분할\n60~600 토큰\n겹침 60토큰"]
    CHUNK --> META["메타데이터 부여\n섹션 경로, 페이지, 유형"]
    META --> FILTER["비분석 청크 제외\n목차, 약어표"]
    FILTER --> TEMP["Neo4j 임시 저장\nTempITB, TempITBChunk"]
    TEMP --> LLM["GPT-4.1 엔티티 추출\n2단계 프로세스\n+ Self-Reflection"]
    LLM --> REGEX["정규식 보완 매칭"]
    REGEX --> ENTITY["추출된 엔티티\nWork Component\nDeliverable\nStandard"]

    ENTITY --> EXACT["정확 매칭\nExact Match"]
    ENTITY --> FUZZY["퍼지 매칭\nFuzzy ≥ 0.85"]
    ENTITY --> ALIAS["약어 테이블 조회\nSTG → Steam Turbine Generator"]
    EXACT --> CORR["CORRESPOND_TO 관계 생성"]
    FUZZY --> CORR
    ALIAS --> CORR
    CORR --> CAND["TempDeliverableRequirement\n후보 생성\nWork Component × Deliverable"]

    CAND --> T1["Tier 1: DR 직접 매칭\n유사도 ≥ 80%"]
    CAND --> T2["Tier 2: 원본 청크 매칭\n유사도 ≥ 80%"]
    CAND --> T3["Tier 3: WC 앵커 매칭\n유사도 ≥ 70%"]
    T1 --> MERGE["결과 병합 + 중복 제거"]
    T2 --> MERGE
    T3 --> MERGE
    MERGE --> CONF["Confidence Score 산출\nmax(LLM, NPMI, 임베딩)"]
    CONF --> PRE["Pre-MDL 출력\n도서명 + Confidence + 출처 페이지"]

    NEO_REF[("Neo4j\n기준 MDL 데이터")] -.->|참조| EXACT
    NEO_REF -.->|참조| FUZZY
    NEO_REF -.->|HNSW 검색| T1
    NEO_REF -.->|HNSW 검색| T2
    NEO_REF -.->|HNSW 검색| T3

    style ITB_UP fill:#e3f2fd,stroke:#1565c0
    style PRE fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style LLM fill:#fff3e0,stroke:#e65100
    style T1 fill:#fce4ec,stroke:#c62828
    style T2 fill:#fce4ec,stroke:#c62828
    style T3 fill:#fce4ec,stroke:#c62828
```

---

## 4. MDL 일정 생성 상세 흐름 (4단계)

```mermaid
flowchart TB
    L3_UP["📊 L3 Schedule 업로드"] --> NTP_EX["NTP 일자 추출\n우선순위: NTP > LNTP > Initial LNTP > PNTP > Baseline"]
    PRE_MDL["Pre-MDL\n(3단계 출력)"] --> TEXT_P["텍스트 전처리\n약어 확장, 특수문자 정리"]
    TEXT_P --> EMB["임베딩 생성\ntext-embedding-3-large"]

    EMB --> BM25["BM25 키워드 검색\n가중치 × 1.0"]
    EMB --> SEM["Semantic 벡터 검색\n가중치 × 30.0"]
    BM25 --> HYBRID["Hybrid Score 산출\nBM25 + Semantic"]
    SEM --> HYBRID
    HYBRID --> TOP5["상위 5개 후보 선별\n임계값 ≥ 45"]

    MILVUS_REF[("Milvus\n이력 도서 임베딩")] -.->|참조| SEM
    BM25_REF[("BM25 인덱스\n이력 도서")] -.->|참조| BM25

    subgraph PREDICT["일정 예측"]
        direction TB
        HAS_SIM{"유사 도서\n존재 여부"}
        HAS_SIM -->|있음| WA["가중 평균 산출\nNTP_to_FA, FA_to_FC\nHybrid Score 가중"]
        HAS_SIM -->|없음| LGB["LightGBM 예측\nConfidence = 0"]
        WA --> FA_CALC["FA = NTP + 예측 NTP_to_FA"]
        LGB --> FA_CALC
        FA_CALC --> FC_CALC["FC = FA + 예측 FA_to_FC"]
        FC_CALC --> CONF_CALC["Confidence Score\nexp(-α × 표준편차)"]
    end

    NTP_EX --> FA_CALC
    TOP5 --> HAS_SIM
    CONF_CALC --> MDL_OUT["일정 포함 MDL 출력\nFA, FC, conf_FA, conf_FC\n예측 근거 설명"]

    style L3_UP fill:#e3f2fd,stroke:#1565c0
    style PRE_MDL fill:#e8f5e9,stroke:#2e7d32
    style MDL_OUT fill:#fff8e1,stroke:#f57f17,stroke-width:2px
    style HYBRID fill:#f3e5f5,stroke:#6a1b9a
```

---

## 5. MDL - L3 일정 비교 상세 흐름 (5단계)

```mermaid
flowchart TB
    MDL_IN["일정 포함 MDL\n(4단계 출력)"] --> WBS["L3 WBS 계층 구조 파싱\nRank1~Rank7 Item 추출"]
    L3_IN["📊 L3 Schedule"] --> WBS

    WBS --> EMB_L3["L3 Item 임베딩 생성"]
    MDL_IN --> EMB_MDL["MDL 도서명 임베딩 생성"]
    EMB_L3 --> COS["코사인 유사도 계산\n임계값 ≥ 0.35"]
    EMB_MDL --> COS
    COS --> VRUL["Validation Rule 필터링\n3단계 우선순위\nPriority 1 → 2 → 3"]
    VRUL --> DATE_SEL["일정 기반 Activity 선택\n일반: Earliest Start\nP.O: Latest Start"]
    DATE_SEL --> MATCH1{"매칭 결과"}

    MATCH1 -->|매칭 성공| MATCHED["매칭된 도서"]
    MATCH1 -->|Unmatch| SC_MATCH["System Code 2차 매칭"]

    subgraph SC["System Code 기반 2차 매칭"]
        direction TB
        SC_MATCH --> MDL_SC["MDL 도서명 → System Code\n임베딩 유사도 ≥ 0.3"]
        SC_MATCH --> L3_SC["L3 Trimmed ID → System Code\n정규식 F{4자리}W 패턴"]
        MDL_SC --> SC_JOIN["동일 System Code\nActivity 필터링"]
        L3_SC --> SC_JOIN
        SC_JOIN --> VRUL2["Validation Rule 필터링\n+ 일정 기반 선택"]
    end

    VRUL2 --> MERGED["전체 매칭 결과 병합"]
    MATCHED --> MERGED

    MERGED --> VAL["Over/Under Validation"]
    subgraph VALIDATION["Validation 판정"]
        direction TB
        VAL --> PARSE_R["Validation Rule 파싱\n시간 단위 변환\nD/W/M/Y → 일수"]
        PARSE_R --> COMPARE["FA/FC vs Start/Finish\n적정 범위 비교"]
        COMPARE --> VALID["✅ Valid\n범위 내"]
        COMPARE --> EXT_V["🟡 Extended Valid\n확장 범위 내"]
        COMPARE --> OVER["🔴 Over\n상한 초과"]
        COMPARE --> UNDER["🔵 Under\n하한 미달"]
        COMPARE --> UNMATCH_V["⚪ Unmatch\n매칭 실패"]
    end

    VALID --> FB
    EXT_V --> FB
    OVER --> FB
    UNDER --> FB
    UNMATCH_V --> FB

    subgraph FEEDBACK["사용자 피드백"]
        direction TB
        FB["리포트 생성\nDocument No, Title\nFA, FC, Activity\nValidation Code"]
        FB --> USER_R{"사용자 검토"}
        USER_R -->|OK| KEEP["일정 확정"]
        USER_R -->|Not OK| EDIT["일정 수정\nFA/FC 변경\nTrimmed ID 변경"]
        EDIT --> REVAL["Validation 재적용"]
        REVAL --> KEEP
    end

    KEEP --> FINAL["📋 최종 MDL Report\nExcel 다운로드"]

    style MDL_IN fill:#fff8e1,stroke:#f57f17
    style L3_IN fill:#e3f2fd,stroke:#1565c0
    style FINAL fill:#e8f5e9,stroke:#2e7d32,stroke-width:3px
    style OVER fill:#ffebee,stroke:#c62828
    style UNDER fill:#e3f2fd,stroke:#1565c0
    style VALID fill:#e8f5e9,stroke:#2e7d32
```

---

## 6. 데이터 저장소 구성도

```mermaid
flowchart LR
    subgraph NEO["Neo4j Graph Database"]
        direction TB
        N1["Plant 노드"]
        N2["ITB 노드"]
        N3["ITBChunk 노드\n+ chunk_text_embedding"]
        N4["ITBWorkComponent 노드\n+ description_embedding"]
        N5["WorkComponent 노드\n+ requirement_embedding"]
        N6["Deliverable 노드\n+ name_embedding"]
        N7["Standard 노드\n+ name_embedding"]
        N8["DeliverableRequirement 노드\n+ HNSW Vector Index"]
        N1 --- N2 --- N3
        N3 --- N4
        N4 -->|"CORRESPOND_TO"| N5
        N5 --- N6
        N5 --- N7
        N5 --- N8
    end

    subgraph MIL["Milvus Vector Database"]
        direction TB
        M1["이력 도서명\n임베딩 벡터\n1536차원"]
        M2["임베딩 캐시\ntext → embedding"]
    end

    subgraph FS["파일 시스템"]
        direction TB
        F1["BM25 인덱스"]
        F2["LightGBM 모델\nlightgbm_emb_NTP_to_FA.pkl\nlightgbm_emb_FA_to_FC.pkl"]
        F3["System Code 사전\nsystemcode.tsv"]
        F4["Validation Rule\nvalidation_rule.csv"]
        F5["약어 테이블\nViết tắt.xlsx"]
    end
```
