# Doosan MDL 프로젝트 온보딩 문서

이 문서는 이 저장소를 처음 보는 개발자가 프로젝트의 목적, 현재 상태, 데이터 흐름, 폴더 구조, 주요 스크립트, 산출물, 개발 시 주의점을 한 번에 이해할 수 있도록 정리한 문서입니다.

## 1. 프로젝트 한 줄 요약

이 프로젝트는 발전 플랜트 입찰/계약 문서인 ITB와 과거 프로젝트의 MDL 데이터를 활용해, 신규 프로젝트에 필요한 Master Document List(MDL) 초안과 표준 도서 목록을 자동 생성하거나 매칭하기 위한 실험/검증 워크스페이스입니다.

현재 저장소의 중심 작업은 다음입니다.

```text
과거 프로젝트 MDL Excel
  -> AI/규칙 기반 분류
  -> 7개 프로젝트 classified MDL CSV 생성
  -> classified MDL을 통합해 Standard MDL 후보 생성
  -> Vendor/EPC, Package/Scope 단위로 LLM 재구성
  -> Standard MDL과 L3/Guide Schedule Activity 매칭
  -> FA / FC / FI 제출 Date Range 생성
  -> 검토 가능한 Excel/CSV 산출물 생성
```

## 2. 이 프로젝트가 해결하려는 문제

플랜트 프로젝트를 시작하면 발주처가 제공하는 ITB(Invitation To Bid), 계약서, 사양서 등을 분석해 어떤 설계/구매/시공 문서가 필요한지 MDL(Master Document List)을 만들어야 합니다.

기존 방식은 엔지니어가 수백~수천 페이지의 문서를 읽고, 과거 프로젝트의 MDL을 참고해 수작업으로 도서 목록을 만드는 구조였습니다. 이 방식은 시간이 오래 걸리고, 담당자 경험에 따라 누락이나 중복이 생길 수 있습니다.

이 프로젝트의 목표는 다음과 같습니다.

- 과거 프로젝트 MDL을 구조화하고 표준화합니다.
- ITB 또는 package keyword를 기준으로 관련 도서 목록을 자동 추천합니다.
- Vendor Document List와 EPC Document List를 분리합니다.
- 출처가 있는 source-grounded 결과와 LLM/전문가 보완이 필요한 결과를 구분합니다.
- 최종 결과는 엔지니어가 검토 가능한 Excel/CSV 형태로 제공합니다.

## 3. 핵심 용어

| 용어 | 의미 |
| --- | --- |
| ITB | Invitation To Bid. 발주처가 제공하는 입찰/계약 요구사항 문서입니다. |
| MDL | Master Document List. 프로젝트 수행에 필요한 문서 목록입니다. |
| Classified MDL | 원본 MDL의 각 도서 행을 Equipment, Building, System, Deliverable 등으로 분류한 CSV입니다. |
| Standard MDL | 여러 프로젝트의 classified MDL을 통합해 표준화한 도서 목록 후보입니다. |
| Vendor Document List | ACC, HRSG, DCS, Pump 등 벤더 패키지 단위의 도서 목록입니다. |
| EPC Document List | EPC 수행 범위에 해당하는 설계/시공/관리 문서 목록입니다. |
| Work Component | 설비, 시스템, 건물, 패키지 등 도서가 대상으로 삼는 객체입니다. |
| Deliverable | Drawing, Data Sheet, Calculation, Manual 같은 문서 유형입니다. |
| L1/L2/L3 | 표준 MDL의 계층입니다. 현재 L1/L2는 강제 taxonomy를 따르고, L3는 LLM이 더 구체적인 장비/객체명으로 생성하는 방향입니다. |
| Level 3 Schedule (L3) | 프로젝트 세부 공정 일정표입니다. 여기서 L3는 MDL 계층의 Equipment (L3)가 아니라 schedule level을 뜻합니다. |
| FA | First Approval 또는 최초 제출/승인 기준 일정입니다. |
| FC | Final Comment 또는 최종 코멘트/승인 기준 일정입니다. |
| FI | For Information 제출 기준 일정입니다. |
| NTP | Notice To Proceed. 프로젝트 착수 기준일로 legacy 일정 예측에서 사용됐습니다. |
| Trimmed ID | L3 Activity 식별 코드입니다. legacy에서는 System Code와 Work Code를 추출하는 데 사용했습니다. |
| Source-Grounded | 과거 MDL 원문 행에 근거가 있는 결과입니다. |
| Expert-Inferred / Needs Doosan Review | 원문 근거가 약하거나 LLM/전문가 보완 성격이 있어 두산 검토가 필요한 결과입니다. |

## 4. 현재 저장소에서 가장 중요한 위치

이 저장소는 실험과 참고자료가 함께 있는 워크스페이스입니다. 현재 개발 기준점은 `00_current_work/current_test_env/`입니다.

| 경로 | 역할 |
| --- | --- |
| `00_current_work/current_test_env/` | 현재 실행 가능한 테스트 환경입니다. 스크립트, prompt, 입력 데이터, 산출물이 이곳에 있습니다. |
| `00_current_work/current_test_env/mdl_runtime/` | 설정, Neo4j 연결, Azure OpenAI embedding 등 공통 런타임 helper입니다. |
| `00_current_work/current_test_env/data/` | 현재 테스트 환경에서 사용하는 MDL Excel, abbreviation, taxonomy docx, ITB chunk JSON 등입니다. |
| `00_current_work/current_test_env/output/` | classified MDL과 Standard MDL 산출물이 저장됩니다. |
| `00_current_work/current_test_env/docs/` | 현재 작업 관련 인수인계/체크리스트 문서입니다. |
| `03_reference_docs/` | 제안서, 두산 피드백 prompt, 시스템 설명 문서, vendor 참고자료 등입니다. |
| `04_data/` | 프로젝트별 원천/샘플 문서와 source archive입니다. |
| `output/` | 일부 별도 검증/매칭 결과가 루트 output에도 존재합니다. |
| `src/` | 현재 활성 소스가 아니라 package metadata/generated cache에 가깝습니다. 개발 기준으로 보지 않습니다. |
| `.codex/FIX_LOG.md` | 세션별 작업 로그입니다. Git ignore 대상이므로 로컬 인수인계용입니다. |

## 5. 현재 활성 테스트 환경 구조

```text
00_current_work/current_test_env/
  build_standard_mdl.py
  build_package_grouped_llm_pilot.py
  build_vendor_package_master_candidate.py
  classify_mdl_v5-2.py
  organize_workspace_archive.py
  ccpp_document_classification_prompt_260423.md
  pyproject.toml
  requirements.txt
  uv.lock
  data/
  docs/
  mdl_runtime/
  output/
```

현재 핵심 스크립트는 4개입니다.

| 파일 | 역할 |
| --- | --- |
| `classify_mdl_v5-2.py` | MDL Excel을 읽고 AI prompt로 각 행을 Equipment, Building, System, Study/Survey, Others, Deliverable 등으로 분류합니다. |
| `build_standard_mdl.py` | 7개 classified MDL CSV를 통합해 source-grounded Standard MDL 후보, audit, validation, rejection 파일을 생성합니다. |
| `build_package_grouped_llm_pilot.py` | Standard MDL 후보를 package/scope group 단위로 줄인 뒤 LLM으로 병합/표준화/보완합니다. 현재 가장 중요한 실험 스크립트입니다. |
| `build_vendor_package_master_candidate.py` | classified MDL의 Equipment 값을 집계해 vendor package master 후보와 review-needed 목록을 만듭니다. |

## 6. 주요 입력 데이터

### 6.1 Classified MDL 생성 전 원본

현재 테스트 환경의 MDL 원본 Excel은 `00_current_work/current_test_env/data/` 아래에 있습니다.

```text
Fadhili_MDL.xlsx
Grati_MDL.xlsx
Karabatan_MDL.xlsm
Muara Tawar_MDL.xlsx
R&N_MDL.xlsx
R&N_MDL_260612.xlsx
Turkistan_MDL.xlsx
Ukudu_MDL.xlsx
```

### 6.2 Classified MDL 입력

Standard MDL 생성의 직접 입력은 `output/*_MDL_classified.csv`입니다.

```text
00_current_work/current_test_env/output/Fadhili_MDL_classified.csv
00_current_work/current_test_env/output/Grati_MDL_classified.csv
00_current_work/current_test_env/output/Karabatan_MDL_classified.csv
00_current_work/current_test_env/output/Muara Tawar_MDL_classified.csv
00_current_work/current_test_env/output/R&N_MDL_classified.csv
00_current_work/current_test_env/output/R&N_MDL_260612_classified.csv
00_current_work/current_test_env/output/Turkistan_MDL_classified.csv
00_current_work/current_test_env/output/Ukudu_MDL_classified.csv
```

`build_standard_mdl.py`와 기본 package-grouped 흐름은 코드상 7개 프로젝트를 기준으로 합니다.

```text
Fadhili, Grati, Karabatan, Muara Tawar, R&N, Turkistan, Ukudu
```

### 6.3 Prompt와 taxonomy

| 파일 | 역할 |
| --- | --- |
| `00_current_work/current_test_env/ccpp_document_classification_prompt_260423.md` | CCPP 도서 분류/표준화에 쓰이는 전문가 prompt 문맥입니다. |
| `00_current_work/current_test_env/data/lv1lv2강제프롬프트.docx` | L1/L2 강제 taxonomy 원천입니다. |
| `03_reference_docs/prompt_feedback/` | 두산 피드백 기반 prompt 문서입니다. |
| `03_reference_docs/6개기준 분류 프롬프트(Doosan Feedback)_20260521.docx` | 최신 분류 기준 참고 문서로 보입니다. |

### 6.4 ITB 관련 데이터

현재 저장소에는 ITB chunk JSON과 원천 문서도 있습니다.

```text
00_current_work/current_test_env/data/itb_chunks/
04_data/sample_documents/project_samples/
```

다만 현재 활성 작업의 중심은 ITB full pipeline 재실행보다 classified MDL 기반 Standard MDL/package list 생성입니다.

## 7. 전체 처리 흐름

### 7.1 1단계: MDL 분류

원본 Excel MDL을 읽고 각 도서 행을 분류합니다.

```text
원본 MDL Excel
  -> classify_mdl_v5-2.py
  -> Azure OpenAI chat model 호출
  -> *_MDL_classified.csv
```

대표 출력 컬럼은 다음입니다.

```text
Source File, Sheet, Document No, Title,
Equipment, Building, System, Study/Survey, Others,
Deliverable, Note
```

### 7.2 2단계: Rule 기반 Standard MDL 후보 생성

7개 classified MDL을 통합해 표준 도서 후보를 만듭니다.

```text
7개 classified MDL CSV
  -> build_standard_mdl.py
  -> source-grounded candidate 생성
  -> Vendor/EPC scope 분리
  -> audit / validation / rejection 출력
```

이 단계의 특징은 다음입니다.

- 속도가 빠르고 재현성이 높습니다.
- 원문 출처 추적이 가능합니다.
- 하지만 결과가 다소 기계적일 수 있습니다.
- 두산 Copilot처럼 engineering 관점에서 재구성된 목록을 만들기에는 한계가 있습니다.

### 7.3 3단계: Package-grouped LLM 표준화

현재 가장 중요한 흐름입니다.

```text
Rule 기반 candidate
  -> package/scope group으로 축소
  -> LLM이 group별 병합/표준화/보완
  -> Excel/CSV 결과 생성
```

이 접근을 쓰는 이유는 다음입니다.

- LLM이 전체 MDL을 한 번에 처리하면 너무 느리고 비용/편차가 큽니다.
- 먼저 규칙으로 후보를 줄이면 source traceability를 유지할 수 있습니다.
- package 단위로 나누면 ACC, HRSG, DCS, Pump 등 엔지니어링 관점의 목록을 만들기 쉽습니다.

### 7.4 4단계: Vendor package master 후보 생성

classified MDL의 Equipment 값을 집계해 어떤 vendor package section을 만들어야 할지 후보를 만듭니다.

```text
classified MDL Equipment column
  -> build_vendor_package_master_candidate.py
  -> canonical package mapping
  -> mapped / review-needed 목록 생성
```

## 8. 현재 구현된 주요 규칙

### 8.1 Vendor / EPC scope 분리

현재 주요 scope는 다음입니다.

```text
Vendor
EPC
```

Vendor는 package 단위로 세분화합니다.

```text
ACC Vendor Document List
HRSG Vendor Document List
DCS Vendor Document List
Pump Vendor Document List
ST/STG Vendor Document List
...
```

### 8.2 L1/L2 강제 taxonomy

`data/lv1lv2강제프롬프트.docx`의 목록을 기준으로 L1/L2를 제한합니다.

- `System (L1)`은 강제 system taxonomy 안에서 선택합니다.
- `Sub-System / Area (L2)`는 Equipment/Building 목록 안에서 선택합니다.
- 적합한 값이 없으면 `General`로 보낼 수 있습니다.

### 8.3 L3는 강제하지 않음

초기에는 L3까지 강제 taxonomy로 제한했지만, 그 결과 L2와 L3가 거의 같아져 계층 구조가 무너졌습니다.

현재 방향은 다음입니다.

```text
L1 = 강제 taxonomy
L2 = 강제 taxonomy
L3 = LLM이 source title과 L1/L2를 보고 구체 장비/객체명 생성
```

예시는 다음입니다.

```text
L2: Air Cooled Condenser
L3: ACC Fan Motor

L2: HRSG
L3: Diverter Damper

L2: DCS
L3: Burner Management System
```

### 8.4 Title 표준화 규칙

현재 title 관련 규칙은 다음 방향입니다.

- `Standardized Document Title`을 단순히 `[L3] + [Document Type]`으로 강제하지 않습니다.
- `Block`, `Unit`, `Project`, `For Block 2` 같은 프로젝트 한정 표현은 제거합니다.
- 원문 title은 `Source Titles`에 보존합니다.
- block만 다른 동일 도서는 병합합니다.
- `Data Sheet & Drawings`는 `Data Sheet`와 `Drawing`으로 분리합니다.
- title에는 산업적으로 익숙한 약어를 허용합니다.

대표 약어:

```text
HRSG, ACC, DCS, GTG, STG, BOP, MOV, P&ID, I&C, MV, LV, UPS
```

## 9. 현재 주요 산출물과 결과 상태

### 9.1 Vendor ACC/HRSG/DCS package-grouped 결과

```text
00_current_work/current_test_env/output/standard_mdl/
  package_grouped_llm_vendor_acc_hrsg_dcs_l12_forced_l3_free/
    package_grouped_standard_mdl.xlsx
    package_grouped_standard_mdl.csv
    package_grouped_audit.csv
    package_grouped_rejections.csv
    package_grouped_validation.csv
```

현재 CSV 기준:

```text
package_grouped_standard_mdl.csv: 437 data rows
```

대표 컬럼:

```text
No, Section, Package/Scope Group, Discipline, Document Type,
System (L1), Sub-System / Area (L2), Equipment (L3),
Standardized Document Title, Scope, Evidence Type, Review Status,
Source Standard Nos, Source Projects, Source Document Nos,
Source Titles, Generation / Merge Reason
```

### 9.2 EPC package-grouped 결과

```text
00_current_work/current_test_env/output/standard_mdl/
  package_grouped_llm_epc_l12_forced_l3_free/
    epc_grouped_standard_mdl.xlsx
    package_grouped_standard_mdl.csv
    package_grouped_audit.csv
    package_grouped_rejections.csv
    package_grouped_validation.csv
```

현재 CSV 기준:

```text
package_grouped_standard_mdl.csv: 4340 data rows
```

### 9.3 Item-level vendor package 결과

현재 별도 item-level run 결과가 있습니다.

```text
00_current_work/current_test_env/output/standard_mdl/item_level_runs/
  pump/
    pump_integrated_mdl_list.xlsx
    pump_integrated_mdl_list.csv
    package_grouped_run_summary.xlsx
    package_grouped_run_summary.csv
  st_stg/
    st_stg_integrated_mdl_list.xlsx
    st_stg_integrated_mdl_list.csv
    package_grouped_run_summary.xlsx
    package_grouped_run_summary.csv
```

현재 CSV 기준:

```text
pump_integrated_mdl_list.csv: 503 data rows
st_stg_integrated_mdl_list.csv: 313 data rows
```

작업 로그 기준 Pump 실행 결과:

```text
source_rows: 1117
candidate_rows: 470
output_rows: 503
rejections: 0
Approved Source-Grounded: 474
Needs Doosan Review: 29
```

### 9.4 Vendor package master 후보

```text
00_current_work/current_test_env/output/standard_mdl/
  vendor_package_master_candidate/
    vendor_package_master_candidate.xlsx
    vendor_package_master_candidate.csv
    vendor_package_master_review_needed.csv
    vendor_package_master_candidate_260618_DoosanFeedback.xlsx
```

현재 CSV 기준:

```text
vendor_package_master_candidate.csv: 735 data rows
vendor_package_master_review_needed.csv: 229 data rows
```

이 산출물은 어떤 vendor package section을 추가로 만들어야 하는지 결정할 때 참고합니다.

### 7.5 5단계: L3/Guide Schedule 기반 MDL 일정 생성

통합 Standard MDL 또는 package별 integrated MDL이 생성된 이후에는, 각 도서에 제출 일정 정보를 붙이는 작업이 필요합니다. 여기서 말하는 L3는 `Equipment (L3)` 계층이 아니라 **Level 3 Schedule**, 즉 프로젝트 공정 일정표를 의미합니다.

목표 흐름은 다음입니다.

```text
Standard MDL / Package Integrated MDL
  -> CCPP Guide Schedule 또는 프로젝트 L3 Schedule Activity와 매칭
  -> 기준 Activity Date 선택
     예: PO Finish, NTP, ICOD, PCOD
  -> 도서 status/type별 제출 rule 적용
     예: FA = PO + N주, FC = FA + 약 2개월, FI = 별도 기준
  -> 단일 날짜가 아니라 FA / FC / FI Date Range 생성
  -> 사용자가 range 안에서 실제 제출일 선택
  -> 일정 포함 MDL Excel 출력
```

이 단계는 “일정 추출”이 아니라 **표준 schedule 기반 date range 생성 엔진**으로 보는 것이 맞습니다.

legacy 1차 POC에는 관련 구현이 있습니다.

```text
01_legacy_poc/master-document-list-project-main/lts/
```

legacy의 기능은 크게 두 축입니다.

```text
1. 과거 실적 기반 FA/FC 날짜 예측
2. MDL 도서와 L3 Activity 매칭 및 일정 validation
```

첫 번째 축은 `src/features/date_generation/` 아래에 있습니다.

```text
src/features/date_generation/basic/hybrid_search.py
src/features/date_generation/basic/keyword_search.py
src/features/date_generation/basic/semantic_search.py
src/features/date_generation/advanced/lightgbm_model.py
src/features/preprocessing/preprocess.py
```

legacy 방식은 과거 프로젝트의 MDL + L3 Schedule 쌍을 전처리해 `NTP_to_FA`, `FA_to_FC`, `NTP_to_FC`를 만들고, 신규 MDL title과 유사한 과거 도서를 BM25 + embedding hybrid search로 찾은 뒤 FA/FC를 예측합니다. 유사 도서가 없으면 LightGBM 모델로 fallback 예측합니다.

이 방식은 참고는 가능하지만, 현재 2차 프로젝트의 공식 기준으로 그대로 사용하면 안 됩니다. 과거 실적 일정에는 프로젝트별 지연, 발주처 차이, COVID, 전쟁, 태풍 등 비표준 요인이 섞여 있기 때문입니다.

두 번째 축은 `src/features/mdl_l3_matching/` 아래에 있습니다.

```text
src/features/mdl_l3_matching/validation_rule.csv
src/features/mdl_l3_matching/systemcode.tsv
src/features/mdl_l3_matching/work.edited.tsv
src/features/mdl_l3_matching/new_rules/matching_pipeline.py
src/features/mdl_l3_matching/new_rules/matching.py
src/features/mdl_l3_matching/new_rules/matching_solution3.py
src/features/validation/assign_label.py
src/features/validation/validate.py
```

이쪽은 현재 프로젝트에 더 직접적으로 재사용할 가치가 있습니다. 핵심은 다음입니다.

- MDL title에서 item과 document name을 파싱합니다.
- L3 WBS hierarchy에서 Activity item을 추출합니다.
- MDL 도서와 L3 Activity를 semantic search로 1차 매칭합니다.
- 미매칭 건은 `Trimmed ID`에서 System Code / Work Code를 추출해 2차 보완 매칭합니다.
- `validation_rule.csv`의 rule로 Activity `Start`/`Finish`와 MDL `FA`/`FC`를 비교합니다.
- 결과를 `Valid`, `Extended Valid`, `Under`, `Over`, `Unmatch` 등으로 분류합니다.

`validation_rule.csv`는 다음 성격의 rule table입니다.

```text
MDL Document Keyword
  -> Activity Keyword
  -> Purpose(FA/FC/FI 등)
  -> Date_choice(Max/Min 등)
  -> Validation Time
```

예시:

```text
MDL Document Keyword: P&ID for Water Treatment System
Activity Keyword: P.O
Purpose: FA
Date_choice: Max
Validation Time: start+1M<=FA<=start+1M+2M
```

즉, 특정 도서는 어떤 L3 Activity를 기준으로 삼고, 그 Activity 기준일에서 얼마 뒤까지 FA가 와야 하는지를 표현합니다.

현재 프로젝트에 적용할 때의 판단은 다음입니다.

| 구분 | 처리 방향 |
| --- | --- |
| legacy 과거 실적 기반 FA/FC 예측 | 직접 사용하지 않고 참고용으로만 봅니다. |
| `validation_rule.csv` | CCPP Guide Schedule 기반 rule table 초안으로 재사용 가능합니다. |
| `systemcode.tsv`, `work.edited.tsv` | L3 Activity ID/Trimmed ID 해석용 참고 사전으로 재사용 가능합니다. |
| `new_rules` matching pipeline | semantic matching + system code fallback 구조를 참고해 새 구현에 반영할 수 있습니다. |
| `assign_label.py` | `start+1M<=FA<=start+3M` 같은 validation expression parser로 재사용 가치가 큽니다. |

이 단계 구현에 필요한 추가 자료는 아직 명확히 확정되어야 합니다.

```text
- 표준 CCPP Guide Schedule 원본
- Activity ID가 명확한 Guide Schedule
- 루마나리아 L2 Schedule 또는 실제 프로젝트 L3/L4 Schedule
- MDL 도서 ↔ Activity ID ↔ 기준일 ↔ PO+Week Offset 매핑표
- FA / FC / FI 대상 도서 판정 기준
- Date Range 폭 기준
- PO Finish, NTP, ICOD, PCOD 중 어떤 기준일을 쓰는지에 대한 rule
- 최종 일정 포함 MDL Excel template
```

### 9.5 Rule 기반 Standard MDL 산출물

```text
00_current_work/current_test_env/output/standard_mdl/
  validation_report.csv
  rejections.csv
  source_mapping_audit.csv
```

`build_standard_mdl.py` 실행 결과의 검증/거절/출처 추적 파일입니다.

## 10. 지금까지 진행한 절차 요약

현재까지 확인되는 흐름은 다음입니다.

1. 7개 프로젝트 MDL을 classified CSV로 변환했습니다.
2. Rule 기반으로 7개 classified MDL을 통합해 Standard MDL 후보를 생성했습니다.
3. 단순 rule 통합은 빠르지만 engineering 기준의 재구성이 약하다는 한계를 확인했습니다.
4. LLM이 전체를 한 번에 통합하는 방식은 너무 오래 걸리고 확장성이 낮다는 점을 확인했습니다.
5. 현재는 `rule 기반 후보 축소 + package/group별 LLM 재구성` 방식으로 전환했습니다.
6. ACC/HRSG/DCS vendor package 결과를 생성했습니다.
7. EPC 범위 결과를 별도 생성했습니다.
8. ST/STG, Pump item-level vendor 결과를 추가 생성했습니다.
9. Vendor package master 후보를 만들어 다음 package 실행 우선순위를 잡고 있습니다.
10. 통합 MDL 생성 이후에는 L3/Guide Schedule 기반 FA/FC/FI Date Range 생성 기능이 추가되어야 함을 확인했습니다.
11. legacy POC의 일정 생성/MDL-L3 매칭 코드를 분석했고, 과거 실적 예측은 참고용, validation rule과 matching 구조는 재사용 후보로 판단했습니다.

## 11. 이전 시행착오와 현재 판단

### 11.1 Rule-only 방식

장점:

- 빠릅니다.
- 재현성이 좋습니다.
- source title과 document no 추적이 쉽습니다.

한계:

- 원문 제목을 정리하는 수준에 머무르기 쉽습니다.
- 엔지니어링 관점의 package 구조 재구성이 약합니다.
- Copilot식 output과 비교하면 표준 목록처럼 보이는 힘이 부족합니다.

### 11.2 LLM-first 방식

장점:

- 결과가 더 자연스럽고 engineering list처럼 보일 수 있습니다.

한계:

- R&N + Fadhili 2개 프로젝트만으로도 오래 걸린 이력이 있습니다.
- 7개 프로젝트 전체로 확장하면 시간/비용/편차가 큽니다.
- source grounding을 검증하기 어렵습니다.

### 11.3 현재 방식

현재 가장 현실적인 방식은 다음입니다.

```text
Rule-based candidate reduction
  + Package/Scope grouping
  + LLM standardization
  + Source-grounding validation
  + Doosan review flagging
```

이 방식은 속도, traceability, 결과 품질 사이의 균형이 가장 좋습니다.

## 12. 실행 방법

명령은 특별한 이유가 없으면 `00_current_work/current_test_env/`에서 실행합니다.

```bash
cd 00_current_work/current_test_env
```

### 12.1 환경 준비

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`uv`가 있으면 다음도 가능합니다.

```bash
uv pip install -r requirements.txt
```

필요한 주요 Python 버전/패키지:

```text
Python >= 3.11
pandas
openpyxl
pydantic
openai
python-dotenv
neo4j
tqdm
```

### 12.2 환경변수

`.env.example`을 `.env`로 복사하고 값을 채웁니다.

필수/주요 항목:

```text
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_API_KEY
AZURE_OPENAI_CHAT_API_VERSION
AZURE_OPENAI_CHAT_DEPLOYMENT
AZURE_OPENAI_EMBEDDING_API_VERSION
EMBEDDING_MODEL
EMBEDDING_DIMENSIONS
NEO4J_URI
NEO4J_USER
NEO4J_PASSWORD
NEO4J_DATABASE
```

현재 `mdl_runtime/config.py`의 기본 chat deployment는 `gpt-5.2`로 설정되어 있습니다.

### 12.3 Classified MDL 생성

```bash
python classify_mdl_v5-2.py
```

주의:

- Azure OpenAI API key가 필요합니다.
- 원본 Excel과 prompt path가 상대경로 기준이므로 `current_test_env`에서 실행하는 것이 안전합니다.

### 12.4 Rule 기반 Standard MDL 생성

```bash
python build_standard_mdl.py
```

예상 출력:

```text
output/standard_mdl/
  validation_report.csv
  rejections.csv
  source_mapping_audit.csv
```

### 12.5 Package-grouped LLM 생성

대표 실행 예시는 다음입니다.

```bash
python build_package_grouped_llm_pilot.py --all-projects --vendor-section-title "Pump Vendor Document List"
```

기존 작업 로그에 따르면 Pump 결과는 다음 경로에 생성되었습니다.

```text
output/standard_mdl/item_level_runs/pump/
```

다른 section도 같은 방식으로 실행할 수 있습니다. 정확한 옵션은 스크립트의 `parse_args()`를 확인한 뒤 실행하는 것이 좋습니다.

### 12.6 Vendor package master 후보 생성

```bash
python build_vendor_package_master_candidate.py
```

예상 출력:

```text
output/standard_mdl/vendor_package_master_candidate/
  vendor_package_master_candidate.xlsx
  vendor_package_master_candidate.csv
  vendor_package_master_review_needed.csv
```

## 13. 개발 구조와 코드 작성 원칙

### 13.1 현재 코드 구조

현재는 완성된 application package라기보다 실험/검증 스크립트 중심의 워크스페이스입니다.

- 스크립트는 `current_test_env` 루트에 있습니다.
- 공통 설정과 외부 서비스 helper는 `mdl_runtime/`에 있습니다.
- 입력과 출력은 상대경로에 강하게 의존합니다.
- 따라서 스크립트 실행 위치가 중요합니다.

### 13.2 새 코드를 추가할 때

권장 방향:

- 재사용 로직은 `mdl_runtime/`으로 옮깁니다.
- 특정 workflow 실행 로직은 별도 script로 유지합니다.
- 대량 파일 생성 시 output path를 명확히 분리합니다.
- 결과에는 source traceability 컬럼을 유지합니다.
- LLM 결과는 가능한 한 source id/document no 기반으로 검증합니다.
- 테스트는 live Azure OpenAI/Neo4j에 의존하지 않는 순수 함수부터 분리합니다.

피해야 할 것:

- `src/doosan_mdl.egg-info`를 활성 소스처럼 수정하지 않습니다.
- `.env`, `.venv`, `__pycache__`, 대량 생성물은 요구가 없으면 커밋하지 않습니다.
- 고객 문서나 민감 자료를 불필요하게 복제하지 않습니다.

## 14. 검증 관점

결과를 검토할 때는 단순 행 수보다 아래를 봐야 합니다.

- `rejections.csv`가 비어 있는지 또는 거절 사유가 타당한지
- `validation.csv` 또는 `validation_report.csv`에 invalid L1/L2, title issue가 있는지
- `Source Standard Nos`, `Source Document Nos`, `Source Titles`가 실제 입력과 연결되는지
- `Evidence Type`이 source-grounded와 expert-inferred를 잘 구분하는지
- `Review Status`가 두산 검토 필요 항목을 숨기지 않는지
- `Data Sheet & Drawings` 같은 복합 deliverable이 분리됐는지
- `Block`, `Unit`, `Project` 같은 프로젝트 한정 표현이 title에 남아 있지 않은지
- L2와 L3가 같은 값으로 반복되어 계층이 무너진 항목이 많은지

## 15. 주요 참고 문서

처음 보는 개발자는 아래 순서로 읽으면 됩니다.

1. 이 문서: `PROJECT_ONBOARDING_KO.md`
2. 현재 테스트 환경 README: `00_current_work/current_test_env/README.md`
3. 최신 인수인계 문서: `00_current_work/current_test_env/docs/mdl_project_handoff_ko.md`
4. 폴더 구조 문서: `FOLDER_STRUCTURE.md`
5. 시스템 개념 문서: `03_reference_docs/system_notes/mdl_system_overview.md`
6. 상세 시스템 가이드: `03_reference_docs/system_notes/mdl_system_comprehensive_guide.md`
7. 작업 로그: `.codex/FIX_LOG.md`

## 16. 다음 작업 후보

현재 상태에서 이어갈 만한 작업은 다음입니다.

- `vendor_package_master_review_needed.csv`의 review-needed package를 사람이 검토해 package mapping rule을 보강합니다.
- Pump 다음 실행 대상으로 기록된 Electrical Equipment Vendor Document List를 생성합니다.
- ACC/HRSG/DCS, EPC, ST/STG, Pump 결과의 validation/rejection 파일을 종합 비교합니다.
- 통합 Standard MDL 이후 L3/Guide Schedule 기반 일정 생성 단계를 설계합니다.
- legacy의 `validation_rule.csv`, `systemcode.tsv`, `work.edited.tsv`, `new_rules` matching pipeline을 현재 구조에 맞게 이식할 범위를 결정합니다.
- CCPP Guide Schedule 원본과 MDL 도서 ↔ Activity ID ↔ 기준일 ↔ offset mapping table을 고객에게 요청합니다.
- FA / FC / FI Date Range 생성 rule과 최종 Excel 출력 template을 확정합니다.
- L3가 L2와 동일하거나 너무 generic한 항목을 후처리 규칙으로 잡습니다.
- `build_package_grouped_llm_pilot.py`의 옵션과 output naming을 README에 더 명확히 정리합니다.
- live LLM 없이 돌릴 수 있는 smoke test를 추가해 regression을 줄입니다.

## 17. 개발자가 바로 기억해야 할 핵심

- 현재 기준 작업 폴더는 `00_current_work/current_test_env/`입니다.
- 이 프로젝트의 현재 핵심은 ITB full pipeline보다 classified MDL 기반 Standard MDL/package list 생성입니다.
- 가장 중요한 스크립트는 `build_package_grouped_llm_pilot.py`입니다.
- 결과 품질의 핵심은 source grounding, L1/L2 taxonomy 준수, L3 구체성, title 표준화입니다.
- Standard MDL 생성 이후에는 Level 3 Schedule 기반 FA/FC/FI Date Range 생성이 붙어야 합니다.
- 이때 L3는 MDL 계층의 Equipment (L3)가 아니라 Level 3 Schedule을 의미합니다.
- 생성 결과는 무조건 엔지니어 검토 대상이며, `Needs Doosan Review` 항목을 숨기면 안 됩니다.
- 작업 중 코드, prompt, workflow, output, validation, execution behavior가 바뀌면 `.codex/FIX_LOG.md`에 기록해야 합니다.
