# Master Document List 시스템 종합 가이드

---

## 1. 개념 정의 (용어 포함)

### 1-1. 시스템의 목적

플랜트 건설 프로젝트를 수주하면, 발주처로부터 수신한 **Invitation To Bid (ITB)** 문서를 분석하여 해당 프로젝트에 필요한 **도서 목록(Master Document List)**을 생성해야 합니다. 본 시스템은 이 과정을 **인공지능(Artificial Intelligence) 기반으로 자동화**하여, 엔지니어의 수작업 부담을 줄이고 누락 위험을 최소화합니다.

### 1-2. 핵심 용어 정의

| 용어 (Full Name) | 설명 | 예시 |
|---|---|---|
| **Invitation To Bid (ITB)** | 발주처가 보내는 입찰 초대 문서. 프로젝트 요구사항이 서술형으로 기재됨 | "The HRSG shall include..." |
| **Master Document List (MDL)** | 프로젝트에 필요한 도서(문서) 목록. 행 단위로 도서명이 나열됨 | Piping & Instrument Diagram, Technical Specification 등 |
| **Work Component** | 플랜트를 구성하는 설비/시스템/장치 단위 | HRSG, Steam Turbine, Pump 등 |
| **Deliverable** | 도서의 종류/유형 | Piping & Instrument Diagram, Datasheet, Drawing 등 |
| **Deliverable Requirement** | Work Component + Deliverable의 조합으로 구성된 실제 도서명 | "HRSG - Piping & Instrument Diagram" |
| **Pre-Master Document List (Pre-MDL)** | 시스템이 자동 생성한 Master Document List 초안. 엔지니어의 검토가 필요함 | (시스템 출력물) |
| **참조 Master Document List** | 과거 유사 프로젝트에서 사용된 Master Document List. 신규 프로젝트의 Master Document List를 생성할 때 참고 자료로 활용 | Fadhili 프로젝트 Master Document List |
| **Level 3 Schedule (L3)** | 프로젝트의 세부 공정 일정표. Activity 단위로 일정이 관리됨 | Foundation Work, Erection, Installation 활동 |
| **Notice To Proceed (NTP)** | 프로젝트 착수 통보 일자. 일정 계산의 기준점 | 2024-01-15 |
| **First Approval (FA)** | 도서의 최초 승인 예정일 | 2024-06-15 |
| **Final Comment (FC)** | 도서의 최종 코멘트(승인 완료) 예정일 | 2024-09-30 |
| **Trimmed ID** | Level 3 Schedule의 Activity를 식별하는 코드. System Code와 Work Code 정보가 내장됨 | "0CF0520W10A012" |
| **System Code** | 플랜트의 시스템/설비 분류 코드 (4자리 숫자) | 0520 (HRSG 시스템) |
| **Work Code** | 작업 유형 분류 코드 (2자리 숫자) | 10 (Foundation Work) |
| **Confidence Score** | 시스템이 매칭 결과에 대해 부여하는 신뢰도 점수 (0~1) | 0.92 |
| **Hybrid Search** | 키워드 기반 검색(BM25)과 의미 기반 검색(Semantic Search)을 결합한 복합 검색 방식 | BM25 가중치 × 1.0 + Semantic 가중치 × 30.0 |

### 1-3. 도서명의 구조

Master Document List의 각 행(도서 1건)은 아래 구조로 구성됩니다:

```
도서명 = Work Component + Deliverable
        (무엇에 대한)         (어떤 종류의 문서)

예시:
  "HRSG - Piping & Instrument Diagram"  = HRSG(설비) + Piping & Instrument Diagram(도서 유형)
  "Steam Turbine - Drawing"              = Steam Turbine(설비) + Drawing(도서 유형)
```

---

## 2. 학습용 Data Layer

### 2-1. 개요

학습용 Data Layer는 시스템이 신규 Invitation To Bid 문서를 분석할 때 참조하는 **과거 프로젝트 데이터의 저장·검색 체계**입니다. 이 데이터는 모델을 재학습(Fine-tuning)시키는 것이 아니라, **검색·참조용 Reference 데이터**로 활용됩니다.

> **핵심**: 시스템은 GPT-4.1을 API 호출 방식으로 사용하며, 별도의 모델 학습(Training)은 수행하지 않습니다. 과거 데이터를 Neo4j 그래프 데이터베이스와 Milvus 벡터 데이터베이스에 **인덱싱(Indexing)**하여, 신규 Invitation To Bid 분석 시 **검색·참조(Retrieval)**하는 구조입니다.

### 2-2. 데이터 유형

| 데이터 유형 | 저장소 | 활용 목적 |
|---|---|---|
| **과거 프로젝트 Invitation To Bid** | Neo4j Graph Database | Work Component, Deliverable 등 엔티티와 그 관계를 그래프 구조로 저장하여, 신규 Invitation To Bid에서 추출한 엔티티와 이름 기반 매칭 수행 |
| **과거 프로젝트 Master Document List** | Neo4j Graph Database + HNSW Vector Index | 도서명에서 추출한 Work Component-Deliverable 관계를 저장하고, 임베딩 벡터를 인덱싱하여 벡터 유사도 기반 도서명 매칭 수행 |
| **과거 프로젝트 Master Document List + Level 3 Schedule 쌍** | Milvus Vector Database + 파일 시스템 | 과거 프로젝트의 도서명과 Level 3 일정 정보를 전처리·임베딩하여, 신규 도서에 대한 First Approval/Final Comment 일정 예측 시 참조 |
| **System Code / Work Code 사전** | TSV 파일 (systemcode.tsv, work.edited.tsv) | Trimmed ID에서 추출한 코드를 설비명/작업명과 매핑하기 위한 참조 사전 |
| **Validation Rule** | CSV 파일 (validation_rule.csv) | 도서별 출도 일정의 적정 범위를 정의하는 규칙. Over/Under Validation에 활용 |

### 2-3. 데이터 처리 방식

학습용 Data Layer는 **3개의 인덱싱 파이프라인**을 통해 구축됩니다:

| 파이프라인 | 이름 | 입력 | 처리 방식 | 출력 |
|---|---|---|---|---|
| **Pipeline 1** | 이력 Invitation To Bid 인덱싱 | 과거 프로젝트 Invitation To Bid (PDF) | Docling 파싱 → 청킹 → LLM Named Entity Recognition → Neo4j 인덱싱 | ITBWorkComponent, ITBChunk 노드 및 관계 |
| **Pipeline 2** | 참조 Master Document List 인덱싱 | 과거 프로젝트 Master Document List (Excel/CSV) | 도서명 파싱 → LLM 엔티티 추출 → NPMI Confidence 산출 → 임베딩 벡터 생성 → Neo4j 인덱싱 | WorkComponent, DeliverableRequirement 노드, HNSW Vector Index |
| **학습 데이터 전처리** | 이력 데이터 학습 | 과거 Master Document List + Level 3 Schedule 쌍 | Master Document List-Level 3 전처리 → Notice To Proceed 기준 일수 계산 → 임베딩 생성 → BM25 학습 → Milvus 인덱싱 | 학습용 데이터프레임, BM25 모델, Milvus 벡터 인덱스, LightGBM 모델 |

---

## 3. Master Document List 도서명 생성

### 3-1. 사용자 업로드 신규 Invitation To Bid 및 기준 Master Document List 업로드

- **설명**: 이 단계는 시스템의 분석 프로세스를 시작하는 진입점입니다. 사용자가 새로운 프로젝트의 Invitation To Bid 문서와 참조할 과거 프로젝트(기준 Master Document List)를 지정하여 업로드하는 단계입니다. 이 단계가 수행되어야 하는 이유는, 시스템이 분석 대상(신규 Invitation To Bid)과 참조 범위(기준 Master Document List)를 확보해야 이후 단계의 청킹, 엔티티 추출, 매칭 프로세스를 진행할 수 있기 때문입니다.

- **인풋**:
  - 사용자가 업로드한 **신규 Invitation To Bid** PDF 파일 (수백 페이지의 프로젝트 입찰 요구사항 문서)
  - 사용자가 지정한 **참조 플랜트(Reference Plant)** 이름 (예: "Rumah & Nairyah") 또는 "global" (전체 과거 플랜트 참조)

- **처리 방식**:
  1. 사용자가 웹 인터페이스를 통해 신규 Invitation To Bid PDF 파일을 업로드합니다
  2. 시스템이 고유한 세션 식별자(Session ID)를 생성하여 해당 분석 세션을 추적합니다
  3. 참조 플랜트가 지정되면 해당 플랜트의 학습용 Data Layer Master Document List 데이터만 필터링하여 매칭 대상으로 설정하고, "global"이면 전체 학습용 Data Layer Master Document List 데이터를 매칭 대상으로 설정합니다

- **아웃풋**:
  - **세션 식별자(Session ID)**가 생성되어 이후 모든 단계에서 해당 분석 세션의 데이터를 식별하는 데 활용됩니다
  - **참조 범위(Reference Scope)**가 확정되어, 이후 3-3단계(기준 Master Document List 활용 도서명 1차 생성)과 3-4단계(Master Document List Vector Database 활용 도서명 2차 생성)에서 사용할 매칭 대상 데이터가 결정됩니다

---

### 3-2. 사용자 업로드 신규 Invitation To Bid Chunking 기반 필요 도서명 탐색

- **설명**: 이 단계에서는 사용자가 업로드한 신규 Invitation To Bid 문서를 인공지능이 분석할 수 있는 크기로 분할(Chunking)한 후, 각 분할된 텍스트 조각에서 Work Component, Deliverable, Standard 등 핵심 엔티티를 추출합니다. 이 단계가 수행되어야 하는 이유는, 수백 페이지에 달하는 Invitation To Bid 전문을 한 번에 Large Language Model에 전달하면 정확도가 크게 저하되므로, 의미 단위로 분할하여 각 조각에 대해 정밀한 엔티티 추출을 수행해야 하기 때문입니다.

- **인풋**:
  - 이전 단계(3-1)에서 업로드된 **사용자 업로드 신규 Invitation To Bid PDF 파일**

- **처리 방식**:
  1. **문서 파싱(Parsing)**: Docling 엔진을 사용하여 Invitation To Bid PDF의 레이아웃(표, 그림, 섹션 구조)을 인식하고 텍스트로 변환합니다
  2. **의미 단위 분할(Chunking)**: HybridChunker를 활용하여, 테이블·섹션·그림 경계를 우선적인 기준으로 삼고, 최소 60토큰 ~ 최대 600토큰 범위 내에서 텍스트를 분할합니다. 청크 간 60토큰의 겹침(Overlap)을 두어 문맥이 단절되지 않도록 합니다
  3. **메타데이터 부여**: 각 청크에 소속 섹션 경로(예: "4.3 General Requirements"), 페이지 번호, 청크 유형(본문/표/목록/목차) 정보를 부여합니다
  4. **비분석 청크 제외**: 목차(Table of Contents)나 약어표(Abbreviation) 유형의 청크는 엔티티 추출 대상에서 자동 제외합니다
  5. **임시 노드 저장**: 분할된 청크들을 Neo4j에 TempITB, TempITBChunk 노드로 임시 저장합니다
  6. **Large Language Model 엔티티 추출**: GPT-4.1에 각 청크를 전달하여 Work Component, Deliverable, Standard, Zone, Keyword를 추출합니다. 2단계 프로세스(Entity Extraction → Validation & Refinement)와 자기 검증(Self-Reflection) 기능을 통해 누락된 엔티티를 재추출합니다
  7. **정규식 보완 매칭**: Large Language Model이 놓친 엔티티를 규칙 기반 정규식(Regex) 매칭으로 추가 포착합니다
  8. **추출 엔티티 저장**: 추출된 Work Component, Deliverable 등을 Neo4j에 TempITBWorkComponent, TempDeliverable 노드로 저장합니다

- **아웃풋**:
  - **사용자 업로드 신규 Invitation To Bid에서 추출된 엔티티 목록**: Work Component 목록(예: HRSG, Steam Turbine, Pump 등), Deliverable 목록(예: Piping & Instrument Diagram, Technical Specification 등), 엔티티 간 관계(예: HRSG → DESCRIBE_FOR → Piping & Instrument Diagram)
  - 이 결과물은 Neo4j에 임시 노드(Temp Node)로 저장되며, 다음 단계인 3-3(기준 Master Document List 활용 도서명 1차 생성)에서 학습용 Data Layer의 정규(Canonical) Work Component와 이름 매칭하는 데 직접 활용됩니다

---

### 3-3. 기준 Master Document List 활용 도서명 1차 생성

- **설명**: 이 단계에서는 사용자 업로드 신규 Invitation To Bid에서 추출된 Work Component를 학습용 Data Layer의 기준 Master Document List에 등록된 정규(Canonical) Work Component와 **이름 기반으로 대응(매핑)**시킵니다. 이 단계가 수행되어야 하는 이유는, 신규 Invitation To Bid에서 추출한 엔티티가 과거 Master Document List의 어떤 설비/시스템에 해당하는지를 식별해야, 해당 설비에 필요한 도서 목록을 추론할 수 있기 때문입니다.

- **인풋**:
  - 이전 단계(3-2)에서 Neo4j에 저장된 **사용자 업로드 신규 Invitation To Bid의 TempITBWorkComponent 노드 목록**
  - 학습용 Data Layer의 **기준 Master Document List에서 인덱싱된 정규 WorkComponent 노드 목록** (Pipeline 2의 결과물)

- **처리 방식**:
  1. **정확 매칭(Exact Matching)**: 사용자 업로드 신규 Invitation To Bid에서 추출한 Work Component 이름(예: "HRSG")을 학습용 Data Layer 기준 Master Document List의 정규 Work Component 이름과 직접 비교합니다
  2. **퍼지 매칭(Fuzzy Matching)**: 정확히 일치하지 않는 경우, 문자열 유사도 계산(Fuzzy Matching, 임계값 0.85)을 적용하여 약간의 오타나 표기 차이를 허용합니다
  3. **약어 테이블 조회(Alias Lookup)**: "STG" → "Steam Turbine Generator"와 같이 약어와 정식 명칭 간의 매핑 테이블을 참조하여 변환합니다
  4. **대응 관계 생성**: 매칭이 성공하면 `[TempITBWorkComponent: HRSG] → CORRESPOND_TO → [정규 WorkComponent: HRSG]` 관계를 Neo4j에 생성합니다
  5. **Deliverable Requirement 후보 생성**: 대응된 Work Component와 추출된 Deliverable의 조합(예: HRSG × Piping & Instrument Diagram)으로 TempDeliverableRequirement 노드를 생성합니다

  > 이 단계에서는 **Large Language Model을 사용하지 않으며**, 문자열 유사도 계산과 약어 테이블 기반의 규칙 매칭으로 수행됩니다.

- **아웃풋**:
  - **CORRESPOND_TO 관계**: 사용자 업로드 신규 Invitation To Bid의 Work Component가 학습용 Data Layer 기준 Master Document List의 어떤 정규 Work Component에 대응되는지가 확정됩니다
  - **TempDeliverableRequirement 후보 목록**: Work Component × Deliverable 조합으로 구성된 도서명 후보 목록이 생성됩니다
  - 이 결과물은 다음 단계인 3-4(Master Document List Vector Database 활용 도서명 2차 생성)에서 임베딩 벡터로 변환되어 학습용 Data Layer의 과거 도서명과 벡터 유사도 매칭하는 데 활용됩니다

---

### 3-4. Master Document List Vector Database 활용 도서명 2차 생성

- **설명**: 이 단계에서는 이전 단계에서 생성된 도서명 후보를 학습용 Data Layer의 Vector Database(HNSW 인덱스)에 저장된 과거 도서명들과 **벡터 유사도 기반으로 정밀 매칭**합니다. 이 단계가 수행되어야 하는 이유는, 이름 기반 매칭(3-3단계)만으로는 표현 방식이 다른 유사 도서를 발견하기 어렵고, 의미적 유사도를 고려한 벡터 검색을 통해 매칭 정확도를 높이고 누락을 보완해야 하기 때문입니다.

- **인풋**:
  - 이전 단계(3-3)에서 생성된 **TempDeliverableRequirement 후보 목록**
  - 사용자 업로드 신규 Invitation To Bid의 **원본 청크(TempITBChunk) 데이터**
  - 학습용 Data Layer Neo4j의 **HNSW Vector Index에 저장된 과거 Master Document List 도서명(DeliverableRequirement)의 임베딩 벡터**

- **처리 방식**:
  1. **임베딩 벡터 생성**: TempDeliverableRequirement 후보들과 신규 Invitation To Bid 원본 청크를 text-embedding-3-large 모델(1,536차원)로 벡터 변환합니다
  2. **3단계 매칭 전략 (Tier System)**: Tier 1에서 매칭되지 않은 도서를 Tier 2, Tier 3로 순차적으로 보완하여 도서를 탐색합니다

  | Tier | 전략 | 유사도 기준 | 상세 설명 |
  |:---:|---|:---:|---|
  | **Tier 1** | Deliverable Requirement 직접 매칭 | ≥ 80% | 3-3단계에서 생성된 Work Component-Deliverable 후보 쌍의 임베딩을 학습용 Data Layer 과거 Master Document List의 도서명 임베딩과 k-Nearest Neighbor 벡터 검색(HNSW)으로 비교합니다 |
  | **Tier 2** | 원본 청크 매칭 | ≥ 80% | 신규 Invitation To Bid 원문 청크 자체의 임베딩을 학습용 Data Layer 과거 Master Document List 도서명 임베딩과 직접 비교하여, Tier 1에서 발견하지 못한 도서를 보완합니다 |
  | **Tier 3** | Work Component 앵커 매칭 | ≥ 70% | 3-3단계에서 대응된 Work Component를 기준으로, 해당 Work Component에 속한 학습용 Data Layer 과거 Master Document List의 모든 도서를 후보로 추가합니다 |

  3. **Confidence Score 산출**: 3가지 소스(Large Language Model 추출 신뢰도, 통계적 공동출현 강도(NPMI), 임베딩 유사도)에서 산출된 값 중 최대값을 최종 Confidence Score로 사용합니다

  > 이 단계에서도 **Large Language Model은 사용하지 않으며**, 임베딩 모델(text-embedding-3-large)에 의한 벡터 변환과 수학적 계산(코사인 유사도)으로 수행됩니다.

- **아웃풋**:
  - **Pre-Master Document List (Pre-MDL)**: 시스템이 자동 생성한 Master Document List 초안으로, 각 도서에 대해 아래 정보가 포함됩니다:
    - 도서명 (Work Component + Deliverable 조합)
    - Confidence Score (0~100%, 매칭 정확도)
    - Confidence Source (Tier 1 / Tier 2 / Tier 3 중 어떤 전략으로 매칭되었는지)
    - 출처 페이지 (신규 Invitation To Bid의 어느 페이지에서 발견되었는지)
    - 분야 (Discipline: Mechanical / Electrical 등)
  - 이 결과물은 **4단계(Master Document List 일정 생성)**에서 각 도서에 대한 First Approval/Final Comment 일정을 예측하는 입력으로 활용됩니다

---

## 4. Master Document List 일정 생성

### 4-1. Master Document List 일정 생성 개요

- **설명**: 이 단계에서는 3단계에서 생성된 Pre-Master Document List의 각 도서에 대해, 과거 유사 프로젝트의 일정 이력을 참조하여 **First Approval(최초 승인) 및 Final Comment(최종 승인) 예상 일정을 자동으로 생성**합니다. 이 단계가 수행되어야 하는 이유는, 도서 목록 자체뿐 아니라 각 도서의 출도 일정까지 함께 제시해야 프로젝트 일정 계획의 실효성을 확보할 수 있기 때문입니다.

- **인풋**:
  - 3단계에서 시스템이 생성한 **Pre-Master Document List** (도서명, Document Number, Discipline 등)
  - 사용자가 업로드한 **Level 3 Schedule Excel 파일** (프로젝트 공정 일정표)
  - 학습용 Data Layer의 **이력 데이터**(과거 프로젝트의 Master Document List + Level 3 Schedule 쌍으로 전처리된 데이터)

- **처리 방식**:
  1. **Level 3 Schedule 전처리**: 사용자 업로로드 Level 3 Schedule에서 Notice To Proceed(또는 LNTP/PNTP/Baseline) 일자를 **우선순위 규칙**에 따라 추출하여 일정 계산의 기준일(Base Date)로 설정합니다
  2. **Pre-Master Document List 전처리**: 도서명에 대한 텍스트 전처리(약어 확장, 특수문자 정리 등)를 수행합니다
  3. **임베딩 생성**: Pre-Master Document List의 각 도서명을 text-embedding-3-large 모델로 벡터 변환합니다
  4. **Hybrid Search 기반 유사 도서명 탐색** (4-2 단계 참조)
  5. **Notice To Proceed 일정 편차 Rule 기반 First Approval/Final Comment 일정 1차 생성** (4-3 단계 참조)

- **아웃풋**:
  - **일정이 포함된 Master Document List**: 각 도서에 대해 예측된 First Approval 일자, Final Comment 일자, 각각의 Confidence Score, 예측 근거 설명(Explanation)이 포함된 Master Document List
  - 이 결과물은 5단계(Master Document List-Level 3 일정 비교)에서 Level 3 Schedule과의 정합성을 검증하는 입력으로 활용됩니다

---

### 4-2. Hybrid Search 기반 유사 도서명 탐색

- **설명**: 이 단계에서는 Pre-Master Document List의 각 도서명에 대해, 학습용 Data Layer의 과거 프로젝트 이력 데이터에서 **가장 유사한 도서명을 복합 검색(Hybrid Search)**으로 탐색합니다. 이 단계가 수행되어야 하는 이유는, 과거 유사 도서의 실제 일정 데이터를 참조해야만 신규 도서의 일정을 합리적으로 예측할 수 있기 때문입니다.

- **인풋**:
  - 4-1단계에서 전처리 및 임베딩된 **Pre-Master Document List 도서명 데이터**
  - 학습용 Data Layer Milvus Vector Database에 인덱싱된 **과거 프로젝트 이력 도서명 임베딩 벡터**
  - 학습용 Data Layer 파일 시스템에 저장된 **과거 프로젝트 이력 도서명의 BM25 인덱스**

- **처리 방식**:
  1. **BM25 키워드 검색**: 도서명의 전처리된 텍스트를 기준으로, 학습용 Data Layer 이력 데이터 전체에 대한 BM25 점수를 계산합니다. 이는 키워드 일치도를 측정합니다
  2. **Semantic 벡터 검색**: 도서명의 임베딩 벡터와 학습용 Data Layer 이력 데이터의 임베딩 벡터 간 코사인 유사도를 계산합니다. 이는 의미적 유사도를 측정합니다
  3. **Hybrid Score 산출**: 두 점수를 가중합으로 결합합니다 (BM25 가중치 × 1.0 + Semantic 가중치 × 30.0)
  4. **상위 후보 선별**: Hybrid Score 상위 5개(Top-K) 후보를 선별한 뒤, 임계값(기본 45점) 이상인 후보만 유효 후보로 확정합니다

- **아웃풋**:
  - **도서별 유사 이력 도서 목록**: Pre-Master Document List의 각 도서에 대해, 과거 프로젝트에서 가장 유사한 도서들의 목록(최대 5개)과 각각의 Hybrid Score
  - 각 유사 이력 도서에는 해당 프로젝트에서의 실제 Notice To Proceed 기준 First Approval 편차(NTP_to_FA), First Approval 기준 Final Comment 편차(FA_to_FC), 출처(Source) 정보가 포함됩니다
  - 이 결과물은 다음 단계인 4-3(Notice To Proceed 일정 편차 Rule 기반 First Approval/Final Comment 일정 1차 생성)에서 가중 평균 일정 계산의 입력으로 직접 활용됩니다

---

### 4-3. Notice To Proceed 일정 편차 Rule 기반 First Approval/Final Comment 일정 1차 생성

- **설명**: 이 단계에서는 4-2단계에서 탐색된 유사 이력 도서들의 일정 편차 데이터를 **가중 평균**하여 신규 도서의 First Approval 및 Final Comment 예상 일정을 산출합니다. 유사 이력 도서가 발견되지 않은 경우에는 사전 학습된 LightGBM 모델을 보조 수단으로 활용합니다. 이 단계가 수행되어야 하는 이유는, 검색된 유사 도서의 실제 일정 이력을 통계적으로 종합하여 가장 합리적인 일정 예측값을 도출해야 하기 때문입니다.

- **인풋**:
  - 4-2단계에서 산출된 **도서별 유사 이력 도서 목록과 Hybrid Score**
  - 각 유사 이력 도서의 **Notice To Proceed 기준 First Approval 편차(NTP_to_FA)**, **First Approval 기준 Final Comment 편차(FA_to_FC)** 값
  - 사용자 업로드 Level 3 Schedule에서 추출된 **기준일(Base Date, Notice To Proceed 또는 대체 일자)**
  - (보조) 학습용 Data Layer에 사전 학습된 **LightGBM 회귀 모델** (lightgbm_emb_NTP_to_FA.pkl, lightgbm_emb_FA_to_FC.pkl)

- **처리 방식**:
  1. **유사 도서가 존재하는 경우 (Primary Rule)**:
     - 유효 후보들의 NTP_to_FA 값을 Hybrid Score로 가중 평균하여 예측 NTP_to_FA 편차(일수)를 산출합니다
     - 유효 후보들의 FA_to_FC 값을 Hybrid Score로 가중 평균하여 예측 FA_to_FC 편차(일수)를 산출합니다
     - 예측 First Approval 일자 = 기준일 + 예측 NTP_to_FA 편차(일수)
     - 예측 Final Comment 일자 = 예측 First Approval 일자 + 예측 FA_to_FC 편차(일수)
     - Confidence Score는 예측값과 참조 이력 값들 간의 표준편차를 기반으로 지수 감쇠 함수(exp(-α × 표준편차))로 산출합니다
  2. **유사 도서가 없는 경우 (Advanced Fallback)**:
     - 도서명 임베딩 벡터를 입력으로 LightGBM 모델이 NTP_to_FA와 FA_to_FC를 각각 예측합니다
     - 이 경우 Confidence Score는 0.0으로 설정되어, 엔지니어에게 수동 검토가 필요함을 명시합니다

- **아웃풋**:
  - **일정이 포함된 Pre-Master Document List**: 각 도서에 대해 아래 정보가 추가됩니다:
    - 예측 First Approval 일자 (pred_FA)
    - First Approval Confidence Score (conf_FA)
    - 예측 Final Comment 일자 (pred_FC)
    - Final Comment Confidence Score (conf_FC)
    - 예측 근거 설명 (Explanation): 참조한 유사 도서들의 Document Number, Title, Discipline, 출처, 실제 일정 등
  - 이 결과물은 5단계(Master Document List-Level 3 일정 비교)에서 Level 3 Schedule의 Activity와 매칭하여 일정 정합성을 검증하는 입력으로 활용됩니다

---

## 5. Master Document List - Level 3 일정 비교

### 5-1. Hybrid Search 기반 도서명 - Level 3 Activity 1차 매칭

- **설명**: 이 단계에서는 Master Document List의 각 도서명에 대해, Level 3 Schedule에서 **의미적으로 가장 유사한 Activity를 Semantic Search 기반으로 탐색**합니다. 이 단계가 수행되어야 하는 이유는, Master Document List의 도서명과 Level 3 Schedule의 Activity Name은 동일한 설비/작업을 서로 다른 표현 방식으로 기술하고 있어, 단순 문자열 비교로는 대응 관계를 식별하기 어렵기 때문입니다.

- **인풋**:
  - 4단계에서 일정이 생성된 **Master Document List** (도서명, Document Number, Discipline, 예측 First Approval/Final Comment 등)
  - 사용자가 업로드한 **Level 3 Schedule Excel 파일** (Trimmed ID, Activity Name, Start, Finish 등)
  - Level 3 Schedule의 **WBS 계층 구조(Work Breakdown Structure Hierarchy)** 정보

- **처리 방식**:
  1. **Level 3 Item 추출**: Level 3 Schedule의 WBS 계층 구조(Rank1 ~ Rank7)에서 각 Activity에 해당하는 설비/시스템 항목(Item)을 추출합니다. 부모 Activity가 있는 경우 최하위 Rank의 값을, 없는 경우 하위 2개 Rank를 결합하여 Item을 구성합니다
  2. **임베딩 생성**: Master Document List 도서명(Item 또는 Title)과 Level 3 Item을 각각 text-embedding-3-large 모델로 벡터 변환합니다. Milvus 캐시를 활용하여 동일 텍스트에 대한 재생성을 방지합니다
  3. **코사인 유사도 매칭**: Master Document List 각 도서의 임베딩과 Level 3 전체 Item의 임베딩 간 코사인 유사도를 계산하여, 임계값(0.35) 이상인 Level 3 Activity를 후보로 선별합니다
  4. **Validation Rule 기반 필터링**: 유사 도서에 대응하는 Level 3 Activity 후보 중, Validation Rule에 정의된 Activity Keyword(예: Work, Erection, Installation, Foundation 등)에 해당하는 Activity만 필터링합니다. 3단계 우선순위 규칙(Priority 1 → 2 → 3)에 따라 매칭합니다
  5. **일정 기반 Activity 선택**: 필터링된 Activity가 복수인 경우, 일반적으로 Start 일자가 가장 빠른(Earliest) Activity를 선택합니다. "P.O"(Purchase Order) 키워드인 경우에는 가장 늦은(Latest) Start 일자의 Activity를 선택합니다

- **아웃풋**:
  - **도서별 매칭된 Level 3 Activity 정보**: 각 도서에 대해 매칭된 Activity Name, Trimmed ID, Start 일자, Finish 일자, Validation Time(적정 일정 범위 규칙), Activity Keyword
  - 매칭되지 않은 도서는 "Unmatch"로 표기됩니다
  - 이 결과물 중 "Unmatch" 도서들은 다음 단계인 5-2(Trimmed ID 기반 도서명 - Level 3 Activity 2차 매칭)에서 System Code 기반 매칭을 시도합니다. 매칭된 도서들은 5-3단계(일정 편차 기반 Validation)로 전달됩니다

---

### 5-2. Trimmed ID 기반 도서명 - Level 3 Activity 2차 매칭

- **설명**: 이 단계에서는 5-1단계의 Semantic Search 기반 매칭에서 대응관계를 찾지 못한(Unmatch) 도서들에 대해, **Level 3 Activity의 Trimmed ID에 내장된 System Code를 활용하여 2차 매칭을 수행**합니다. 이 단계가 수행되어야 하는 이유는, 의미적 유사도 검색만으로는 표현 방식이 크게 다른 도서와 Activity 간의 대응관계를 식별하지 못하는 경우가 있어, 구조화된 코드 체계(System Code)를 보조적으로 활용하여 매칭 범위를 확장해야 하기 때문입니다.

- **인풋**:
  - 5-1단계에서 **"Unmatch"로 분류된 Master Document List 도서 목록**
  - 사용자 업로드 **Level 3 Schedule의 전체 Activity 목록** (Trimmed ID, Activity Name, Start, Finish)
  - 학습용 Data Layer **System Code 사전** (systemcode.tsv: 4자리 코드 ↔ 약어 ↔ 정식 명칭 매핑)

- **처리 방식**:
  1. **Master Document List → System Code 매핑**: Master Document List 도서명의 임베딩과 System Code 사전의 약어+정식 명칭 임베딩 간 코사인 유사도를 계산하여, 각 도서에 대해 가장 유사한 System Code를 매칭합니다 (임계값 0.3 이상)
  2. **Level 3 Trimmed ID → System Code 추출**: Level 3 Activity의 Trimmed ID(예: "0CF0520W10A012")에서 정규식 패턴(F{4자리숫자}W)으로 System Code(예: "0520")를 추출합니다
  3. **System Code 기준 Activity 필터링**: Master Document List 도서에 매칭된 System Code와 동일한 System Code를 가진 Level 3 Activity들을 후보로 선별합니다
  4. **Validation Rule 기반 필터링 및 Activity 선택**: 5-1단계와 동일한 3단계 우선순위 Validation Rule 기반으로 Activity Keyword 필터링 및 일정 기반 Activity 선택을 수행합니다

- **아웃풋**:
  - **2차 매칭된 도서별 Level 3 Activity 정보**: 5-1단계에서 Unmatch였던 도서들 중 System Code 기반으로 매칭된 도서들의 Activity Name, Trimmed ID, Start, Finish
  - 5-1단계의 매칭 결과와 5-2단계의 매칭 결과가 **병합**되어, 전체 Master Document List에 대한 Level 3 Activity 매칭 결과가 완성됩니다
  - 이 병합된 결과물은 다음 단계인 5-3(일정 편차 기반 Over/Under Validation)에서 일정 정합성 검증의 입력으로 활용됩니다

---

### 5-3. 표준 Level 3 - Master Document List 일정 편차 기반 Over / Under Validation

- **설명**: 이 단계에서는 Master Document List의 각 도서에 대해, **예측된 First Approval/Final Comment 일정이 매칭된 Level 3 Activity의 Start/Finish 일정과 비교하여 적정 범위 내에 있는지를 검증**합니다. 이 단계가 수행되어야 하는 이유는, Master Document List의 도서 출도 일정(First Approval/Final Comment)이 해당 설비의 시공·조달 일정(Level 3 Activity Start/Finish)과 정합하지 않으면 프로젝트 수행에 차질이 발생할 수 있어, 사전에 이를 탐지하고 엔지니어에게 피드백을 제공해야 하기 때문입니다.

- **인풋**:
  - 5-1 및 5-2단계에서 병합된 **전체 Master Document List-Level 3 매칭 결과** (도서별 First Approval, Final Comment, 매칭된 Activity의 Start, Finish)
  - **Validation Rule** (도서 유형별 적정 일정 범위를 정의하는 규칙표, validation_rule.csv)

- **처리 방식**:
  1. **Validation Rule 파싱**: 도서별로 지정된 Validation Time 규칙(예: "Start+20W <= FA <= Finish-1M")을 파싱하여, First Approval과 Final Comment의 적정 하한(Lower Bound)과 상한(Upper Bound)을 산출합니다. 시간 단위 표현(D=일, W=주, M=월, Y=년)을 일수로 변환합니다
  2. **일정 비교 및 판정**: 각 도서에 대해 아래 기준으로 판정합니다:
     - **Valid**: First Approval과 Final Comment 모두 적정 범위(Lower Bound ~ Upper Bound) 내에 있는 경우
     - **Extended Valid**: 1차 규칙(Valid)에는 해당하지 않으나, 2차 이상의 확장 규칙 범위 내에 있는 경우 (±1개월 여유 등)
     - **Over**: First Approval 또는 Final Comment가 상한(Upper Bound)을 초과한 경우. 초과 일수가 함께 표시됩니다
     - **Under**: First Approval 또는 Final Comment가 하한(Lower Bound) 미만인 경우. 미달 일수가 함께 표시됩니다
  3. **누락 데이터 처리**: Start 또는 Final Comment 일자가 누락된 경우 "No Start", "No FC" 등의 메시지를 표시합니다

- **아웃풋**:
  - **Validation Code**: 각 도서에 대한 판정 결과 (Valid / Extended Valid / Over / Under / Unmatch)
  - **Validation Message**: 판정 근거 상세 (예: "FA > Finish-1M (15 days)" 또는 "FC < Start+20W (7 days)")
  - 이 결과물은 다음 단계인 5-4(도서별 출도 일정 피드백)에서 사용자에게 최종 검토 결과를 제시하는 데 활용됩니다

---

### 5-4. 도서별 출도 일정 피드백 (OK / Not OK)

- **설명**: 이 단계에서는 5-3단계의 Validation 결과를 바탕으로 **사용자(엔지니어)가 각 도서의 출도 일정에 대해 최종 피드백(OK 또는 Not OK)을 제공**하고, 필요 시 일정을 수정하는 단계입니다. 이 단계가 수행되어야 하는 이유는, 시스템이 생성한 Pre-Master Document List와 일정 예측은 어디까지나 초안이며, 도메인 전문가인 엔지니어의 검토와 보정을 거쳐야 최종 산출물로서 의미를 가지기 때문입니다.

- **인풋**:
  - 5-3단계에서 Validation이 완료된 **최종 Report** (도서명, 예측 First Approval/Final Comment, 매칭된 Level 3 Activity, Validation Code/Message 등)
  - 일정 생성 결과 파일(Date Generation Result)과 매칭 결과 파일(Matching Result)이 병합된 통합 리포트

- **처리 방식**:
  1. **리포트 로드**: 일정 생성 결과와 매칭 결과를 병합하여 통합 리포트를 구성합니다. 각 도서에 "User Feedback" 컬럼(초기값 "OK")과 "Comment" 컬럼을 추가합니다
  2. **메트릭스 산출**: 전체 도서에 대한 Over/Under/Valid/Extended Valid/Invalid 비율 등 요약 지표를 계산합니다
  3. **사용자 검토 및 피드백**:
     - 사용자가 각 도서의 일정을 검토하고, 문제가 있는 도서에 대해 **"Not OK"**를 지정합니다
     - "Not OK"로 지정된 도서에 대해 사용자가 직접 First Approval, Final Comment 일자를 수정하거나, Activity ID/Trimmed ID를 변경할 수 있습니다
  4. **변경 사항 적용**: 사용자가 수정한 일정을 반영하고, 변경된 도서에 대해 Validation Rule을 재적용하여 Validation Code를 갱신합니다. Trimmed ID가 변경된 경우, Level 3 Schedule 파일에서 해당 Trimmed ID의 유효성을 검증합니다
  5. **변경 이력 저장**: 수정된 내용을 원본 리포트에 반영하고, 최종 결과물로 저장합니다

- **아웃풋**:
  - **최종 Master Document List 리포트 (Excel)**: 도서명, 예측 일정, 매칭된 Level 3 Activity, Validation 결과, 사용자 피드백(OK/Not OK), 코멘트가 포함된 최종 산출물
  - **메트릭스 요약**: Over/Under/Valid/Extended Valid 비율, 매칭률, Confidence Score 분포 등의 요약 지표
  - 이 최종 산출물은 엔지니어가 다운로드하여 프로젝트 일정 계획에 활용하며, 사용자의 피드백 데이터는 향후 시스템 개선을 위한 참고 자료로 활용될 수 있습니다
