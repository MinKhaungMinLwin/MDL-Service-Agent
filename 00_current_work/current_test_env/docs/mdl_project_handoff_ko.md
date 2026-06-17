# MDL 프로젝트 인수인계 정리

## 프로젝트 목표

기존 7개 프로젝트의 classified MDL을 기반으로 통합 Standard MDL을 만들고, 이후 신규 ITB에서 주요 item/package를 식별해 해당 package의 표준 도서 목록을 자동 생성/매칭하는 것이 목표입니다.

현재 목표 흐름은 다음과 같습니다.

```text
1. 7개 classified MDL 기반 통합 Standard MDL 생성
2. ITB에서 keyword/package 추출 후 관련 Standard MDL section 매칭
3. ITB에 직접 명시되지 않았지만 package 구성상 필요한 문서 보완 매칭
```

현재는 1번, 즉 Standard MDL 생성 방식을 집중 테스트 중입니다.

## 주요 입력 데이터

작업 디렉토리:

```text
00_current_work/current_test_env/
```

7개 classified MDL 입력:

```text
output/Fadhili_MDL_classified.csv
output/Grati_MDL_classified.csv
output/Karabatan_MDL_classified.csv
output/Muara Tawar_MDL_classified.csv
output/R&N_MDL_classified.csv
output/Turkistan_MDL_classified.csv
output/Ukudu_MDL_classified.csv
```

최근 R&N 원본 업데이트 파일:

```text
data/R&N_MDL_260612.xlsx
```

L1/L2 강제 taxonomy 문서:

```text
data/lv1lv2강제프롬프트.docx
```

CCPP 전문가 프롬프트:

```text
ccpp_document_classification_prompt_260423.md
```

두산 Copilot 참고 결과:

```text
output/standard_mdl/Option2 Copilot Result.xlsx
```

## 핵심 스크립트

Rule 기반 Standard MDL 후보 생성:

```text
build_standard_mdl.py
```

현재 package-grouped LLM 생성 스크립트:

```text
build_package_grouped_llm_pilot.py
```

현재 가장 중요한 스크립트입니다. 역할은 다음과 같습니다.

```text
7개 classified MDL
→ rule 기반 source-grounded candidate 생성
→ ACC / HRSG / DCS / EPC group으로 필터링
→ group별 LLM 호출
→ 병합 / 중복 제거 / title 재생성
→ Excel/CSV 출력
```

Vendor package master 초안 생성 스크립트:

```text
build_vendor_package_master_candidate.py
```

## 현재 구현된 주요 규칙

### 1. Vendor / EPC Scope 분리

현재 고정 group:

```text
ACC Vendor Document List
HRSG Vendor Document List
DCS Vendor Document List
EPC Document List
```

최근 테스트에서는 우선 아래 3개만 생성했습니다.

```text
ACC Vendor Document List
HRSG Vendor Document List
DCS Vendor Document List
```

### 2. L1 강제

`System (L1)`은 `lv1lv2강제프롬프트.docx`의 `3. System` 목록 안에서만 선택합니다.

### 3. L2 강제

`Sub-System / Area (L2)`는 docx의 아래 목록 안에서만 선택합니다.

```text
1. Equipment
2. Building
```

없으면 `General`로 분류합니다.

### 4. L3는 강제하지 않음

초기에는 L3도 Section 1/2 taxonomy로 강제했지만, 그 결과 L2와 L3가 거의 동일해져 계층 구조가 무너졌습니다.

현재 방향:

```text
L1 = 강제 taxonomy
L2 = 강제 taxonomy
L3 = LLM이 L1/L2와 source title을 보고 구체 장비/객체로 생성
```

예:

```text
L2: Air Cooled Condenser
L3: ACC Fan Motor

L2: Bypass stack
L3: Diverter Damper

L2: DCS
L3: Burner Management System
```

### 5. Title 규칙

현재 title 관련 규칙:

```text
- Standardized Document Title은 단순히 [L3] + [Document Type]으로 강제하지 않음
- Block / Unit / Project / For Block 2 같은 프로젝트 한정 표현 제거
- 원문 title은 Source Titles에 그대로 보존
- block만 다른 동일 문서는 병합
- Data Sheet & Drawings는 Data Sheet와 Drawing으로 분리
- title에는 약어 사용: HRSG, ACC, DCS, GTG, STG, BOP, MOV, P&ID, I&C 등
```

## 최근 생성 결과

현재 가장 의미 있는 결과:

```text
output/standard_mdl/package_grouped_llm_vendor_acc_hrsg_dcs_l12_forced_l3_llm/package_grouped_standard_mdl.xlsx
```

요약:

```text
rows: 526
ACC: 106
HRSG: 357
DCS: 63
rejections: 0
invalid_l1: 0
invalid_l2: 0
L3 == L2: 9건
For Block / Block qualifier in title: 0
Data Sheet & Drawings remaining: 0
Validation Report: empty
```

Vendor package master 초안:

```text
output/standard_mdl/vendor_package_master_candidate/vendor_package_master_candidate.xlsx
```

## 이전 시행착오

### 1. Rule 기반 통합 방식

`build_standard_mdl.py`는 빠르고 안정적이지만, title이 대부분 `Equipment + Document Type` 수준으로 정리되어 두산 Copilot처럼 엔지니어링 기준으로 재구성된 느낌이 약했습니다.

### 2. LLM-first 방식

R&N + Fadhili 2개 프로젝트만 LLM이 직접 전체 통합하게 테스트했으나 약 2시간 소요되었습니다.

문제:

```text
- 너무 느림
- 전체 7개 프로젝트로 확장 시 시간 부담 큼
- 결과 편차 가능성 큼
```

현재는 아래 방식이 현실적이라고 판단했습니다.

```text
rule 기반 후보 축소 + group별 LLM 재생성
```

### 3. L3 강제 오류

L3를 Section 1/2 taxonomy로 강제했더니 다음처럼 계층성이 사라졌습니다.

```text
L2 = HRSG
L3 = HRSG
```

현재는 L3를 LLM 생성값으로 열어둔 상태입니다.

## 두산 Copilot 결과와의 차이

두산 Copilot 프롬프트는 더 강하게 아래를 요구했습니다.

```text
- Vendor / EPC 완전 분리
- System → Sub-System → Equipment → Document Type 계층 유지
- 기존 도서 나열 금지
- 엔지니어링 기준 재구성
- 누락 문서 적극 보완
- Foundation 문서 강제 생성
```

현재 우리 프롬프트에 반영된 것:

```text
- Vendor/EPC 분리
- 병합/표준화
- L1/L2 강제
- L3 구체 장비 생성
- block qualifier 제거
- Data Sheet & Drawings 분리
- 약어 사용
```

아직 약하거나 미반영인 것:

```text
- Foundation 강제 생성
- Building 상세 분해
- Infrastructure 강제 포함
- Expert-Inferred 누락 문서 적극 생성
```

## 현재 한계

최신 결과는 모두 아래 상태입니다.

```text
Evidence Type = Source-Grounded
Review Status = Approved Source-Grounded
```

즉 LLM이 새 도서를 거의 생성하지 않았습니다.

이유:

```text
- 현재 프롬프트는 source evidence 기반 병합/표준화에 가까움
- package별 expected deliverable checklist가 없음
- Expert-Inferred second pass가 아직 없음
```

누락 문서 보완까지 하려면 다음 단계가 필요합니다.

```text
1차: Source-Grounded 병합/표준화
2차: package별 expected deliverable checklist 기반 gap analysis
3차: 누락 후보를 Expert-Inferred + Needs Doosan Review로 추가
```

## 다음 작업 제안

1. ACC / HRSG / DCS 최신 결과를 두산에 먼저 검토 요청합니다.

검토 포인트:

```text
- L1/L2 분류가 적절한지
- L3가 계층적으로 적절한지
- title이 Copilot 결과와 유사한지
- 너무 세분화/과병합된 항목이 있는지
- Source-Grounded만으로 충분한지
```

2. Generic title validation을 강화합니다.

최종 title로 단독 사용되면 안 되는 값:

```text
Drawing
Calculation
Report
List
Data Sheet
Procedure
Manual
Specification
Diagram
Plan
Layout
```

3. Expert-Inferred second pass를 설계합니다.

필요한 정보:

```text
- package/system/equipment hierarchy
- package별 expected deliverable checklist
- Vendor/EPC 구분 기준
- 누락 문서 생성 허용 범위
```

4. 전체 item/package section으로 확장합니다.

classified MDL + docx taxonomy 기준 section 후보:

```text
전체 section 후보: 173
Equipment 기반: 106
Building 기반: 49
System/Study 기반: 57
General: 1
```

전체를 한 번에 돌리기보다 package 우선순위를 정해야 합니다.

## 실행 예시

ACC/HRSG/DCS만 실행:

```bash
cd 00_current_work/current_test_env

.venv/bin/python build_package_grouped_llm_pilot.py \
  --all-projects \
  --batch-size 40 \
  --max-epc-batches 0 \
  --output-dir output/standard_mdl/package_grouped_llm_vendor_acc_hrsg_dcs_l12_forced_l3_llm
```

EPC 일부 batch 이어서 실행:

```bash
.venv/bin/python build_package_grouped_llm_pilot.py \
  --all-projects \
  --batch-size 40 \
  --epc-only \
  --epc-start-batch 21 \
  --epc-end-batch 40 \
  --output-dir output/standard_mdl/package_grouped_llm_epc_21_40
```

## 현재 기준 결론

현재 가장 적합한 구조는 다음과 같습니다.

```text
classified MDL에서 package 후보 필터링
→ L1/L2는 docx taxonomy로 강제
→ L3는 LLM이 구체 장비/객체로 생성
→ LLM이 package별 병합/중복 제거/title 재생성
→ 후처리로 block/unit 제거, 복합 deliverable 분리, validation
→ 두산 검토 후 기준 확정
```
