# MDL Schedule Generation Summary / Tóm tắt tạo lịch MDL / MDL 일정 생성 요약

## 1. 한국어

### 프로젝트 배경

현재 진행 중인 2차 프로젝트는 1차 POC의 컨셉은 참고하되, 일정 생성 로직은 새로 설계하는 방향입니다. 1차 POC에서는 7개 과거 프로젝트 MDL의 실제 제출 일정을 학습/DB화하고, 유사도 기반으로 신규 MDL의 FA/FC 일정을 예측했습니다. 하지만 프로젝트별 지연 요인과 제출 기준 차이가 섞여 있어 표준 일정으로 사용하기 어렵다는 한계가 확인되었습니다.

따라서 이번 프로젝트의 일정 생성 기준은 과거 실적 일정이 아니라 **표준 CCPP Guide Schedule**입니다.

### 목표 방향

이번 MDL 일정 생성은 단일 날짜 예측이 아니라 **표준 스케줄 기반 Date Range 생성**입니다.

```text
ITB 분석
-> MDL 도서 후보 추출
-> MDL 도서와 CCPP Guide Schedule Activity 매칭
-> 기준 Activity Date 확인, 예: PO Finish Date
-> PO + N주 기준으로 FA / FC / FI Date Range 생성
-> 사용자가 Range 안에서 실제 제출일 선택
-> 일정 포함 MDL Excel 산출
```

핵심 매핑은 다음 세 가지입니다.

- MDL 도서 ↔ CCPP Guide Schedule Activity
- Activity 기준일, 예: PO Finish Date, NTP, ICOD, PCOD
- 도서 Status별 제출 기준, 예: FA = PO + N주, FC = FA + 약 2개월, FI = 별도 기준

### FA / FC / FI 처리 기준

| 구분 | 의미 | 처리 방향 |
| --- | --- | --- |
| FA | 최초 제출 도서 | PO + N주 기준으로 Range 생성 |
| FC | 승인/검토 후 최종 제출 도서 | FA 이후 일정 기간, 예: 약 2개월 기준 Range 생성 |
| FI | For Information 제출 도서 | FI 전용 기준 필요 |
| 제외 대상 | 품질, 구매, 비설계 문서 등 | 고객 피드백 기준으로 필터링 |

### 1차 POC에서 재사용 가능한 자료

1차 POC 내부에 이번 작업에 참고 가능한 자료가 일부 있습니다.

- `lts/src/features/mdl_l3_matching/validation_rule.csv`
  - MDL Document Keyword, Activity Keyword, Purpose, Validation Time이 포함되어 있어 이번 매핑 룰의 초안으로 활용 가능
- `lts/src/features/mdl_l3_matching/systemcode.tsv`
  - 시스템 코드 및 시스템 설명 사전
- `lts/src/features/mdl_l3_matching/work.tsv`
  - Work Code 및 Work Description 사전
- `lts/data/historical_fixed_data/train/*`
  - 기존 프로젝트 L3/MDL 샘플
- `data/sample_documents/.../Fadhili/Fadhili DDCL(MDL).xlsx`
  - Fadhili 기준 MDL 템플릿 후보

다만 1차 POC 자료는 과거 프로젝트 실적 기반이므로, 이번 프로젝트의 공식 기준으로 바로 사용하기보다는 **매핑 룰 초안과 참고 데이터**로 보는 것이 적절합니다.

### 추가 요청이 필요한 자료

현재 폴더 내에서 명확히 확인되지 않은 핵심 자료는 아래입니다.

- 표준 CCPP Guide Schedule 원본
- 루마나리아 L2 Schedule
- 가능하면 L3/L4 상세 Schedule
- Activity ID 기준의 Guide Schedule
- MDL 도서 ↔ Activity ID ↔ 기준일 ↔ PO+Week Offset 매핑표
- FA / FC / FI 대상 도서 판정 기준
- Date Range 폭 기준
- KKS Code 생성 또는 매핑 기준
- 최종 Excel 산출물 템플릿 확정본

### 개발 관점 결론

이번 기능의 핵심은 “일정 추출”이 아니라 **표준 스케줄 기반 일정 Range 생성 엔진**입니다. 우선 `validation_rule.csv`를 분석해 초기 룰 테이블 구조를 만들고, 고객이 제공할 CCPP Guide Schedule과 Activity ID 기준 매핑표를 결합하는 방식으로 설계하는 것이 적절합니다.

---

## 2. Tiếng Việt

### Bối cảnh dự án

Dự án giai đoạn 2 hiện tại sẽ giữ lại khái niệm chính từ POC giai đoạn 1, nhưng logic tạo lịch MDL sẽ được thiết kế lại. Trong POC giai đoạn 1, hệ thống sử dụng dữ liệu lịch nộp thực tế từ 7 dự án MDL trước đây, lưu vào DB và dự đoán ngày FA/FC cho MDL mới bằng phương pháp matching theo độ tương đồng. Tuy nhiên, lịch thực tế của từng dự án bị ảnh hưởng bởi nhiều yếu tố như chậm tiến độ, điều kiện đặc biệt của từng dự án, COVID, thiên tai hoặc chiến tranh, nên không phù hợp để dùng làm lịch chuẩn.

Vì vậy, trong dự án hiện tại, cơ sở tạo lịch sẽ là **CCPP Guide Schedule chuẩn**, không phải lịch thực tế của các dự án cũ.

### Định hướng mục tiêu

Việc tạo lịch MDL lần này không nhằm dự đoán một ngày duy nhất, mà nhằm tạo **Date Range dựa trên schedule chuẩn**.

```text
Phân tích ITB
-> Trích xuất ứng viên tài liệu MDL
-> Match tài liệu MDL với CCPP Guide Schedule Activity
-> Xác định ngày cơ sở của Activity, ví dụ PO Finish Date
-> Tạo FA / FC / FI Date Range theo PO + N tuần
-> Người dùng chọn ngày nộp thực tế trong Range
-> Xuất MDL Excel có thông tin lịch
```

Ba mapping quan trọng cần có là:

- Tài liệu MDL ↔ CCPP Guide Schedule Activity
- Ngày cơ sở của Activity, ví dụ PO Finish Date, NTP, ICOD, PCOD
- Quy tắc nộp theo Status, ví dụ FA = PO + N tuần, FC = FA + khoảng 2 tháng, FI = quy tắc riêng

### Quy tắc xử lý FA / FC / FI

| Loại | Ý nghĩa | Hướng xử lý |
| --- | --- | --- |
| FA | Tài liệu nộp lần đầu | Tạo Range theo PO + N tuần |
| FC | Tài liệu nộp cuối sau khi được review/approve | Tạo Range sau FA, ví dụ khoảng 2 tháng |
| FI | Tài liệu For Information | Cần quy tắc riêng cho FI |
| Loại trừ | Tài liệu quality, procurement, non-design... | Filter theo feedback của khách hàng |

### Tài liệu có thể tái sử dụng từ POC giai đoạn 1

Trong POC giai đoạn 1 có một số tài liệu có thể dùng để tham khảo.

- `lts/src/features/mdl_l3_matching/validation_rule.csv`
  - Có MDL Document Keyword, Activity Keyword, Purpose, Validation Time; có thể dùng làm bản nháp cho rule mapping
- `lts/src/features/mdl_l3_matching/systemcode.tsv`
  - Dictionary cho system code và system description
- `lts/src/features/mdl_l3_matching/work.tsv`
  - Dictionary cho work code và work description
- `lts/data/historical_fixed_data/train/*`
  - Dữ liệu mẫu L3/MDL của các dự án cũ
- `data/sample_documents/.../Fadhili/Fadhili DDCL(MDL).xlsx`
  - Ứng viên template MDL theo format Fadhili

Tuy nhiên, dữ liệu POC giai đoạn 1 chủ yếu dựa trên lịch thực tế của các dự án cũ. Vì vậy, không nên dùng trực tiếp làm tiêu chuẩn chính thức cho dự án hiện tại, mà nên dùng như **dữ liệu tham khảo và bản nháp rule mapping**.

### Tài liệu cần yêu cầu thêm

Các tài liệu quan trọng sau chưa được xác nhận rõ trong folder hiện tại.

- Bản gốc CCPP Guide Schedule chuẩn
- Lumanaria L2 Schedule
- L3/L4 Schedule chi tiết nếu có
- Guide Schedule có Activity ID rõ ràng
- Bảng mapping MDL Document ↔ Activity ID ↔ Base Date ↔ PO+Week Offset
- Quy tắc xác định tài liệu nào là FA / FC / FI
- Quy tắc độ rộng của Date Range
- Quy tắc tạo hoặc mapping KKS Code
- Template Excel output cuối cùng

### Kết luận từ góc nhìn phát triển

Chức năng chính không phải là “trích xuất lịch”, mà là **engine tạo Date Range dựa trên schedule chuẩn**. Bước đầu nên phân tích `validation_rule.csv` để tạo cấu trúc rule table ban đầu, sau đó kết hợp với CCPP Guide Schedule và bảng mapping Activity ID do khách hàng cung cấp.

---

## 3. English

### Project Background

The current phase 2 project will keep the core concept from the phase 1 POC, but the MDL schedule generation logic should be redesigned. In the phase 1 POC, the system used actual submission schedules from 7 historical MDL projects, stored them in a DB, and predicted FA/FC dates for new MDL documents based on similarity matching. However, those historical schedules include project-specific delays and exceptional conditions such as COVID, typhoons, war, and other non-standard factors. As a result, they are not suitable as a standardized scheduling basis.

Therefore, the scheduling basis for the current project should be the **standard CCPP Guide Schedule**, not historical project actual dates.

### Target Direction

The new MDL schedule generation should generate **date ranges based on a standard schedule**, instead of predicting a single due date.

```text
Analyze ITB
-> Extract candidate MDL documents
-> Match MDL documents to CCPP Guide Schedule Activities
-> Identify the base Activity date, e.g. PO Finish Date
-> Generate FA / FC / FI Date Ranges based on PO + N weeks
-> Let users select actual submission dates within the ranges
-> Export MDL Excel with schedule information
```

The key mappings are:

- MDL document ↔ CCPP Guide Schedule Activity
- Activity base date, e.g. PO Finish Date, NTP, ICOD, PCOD
- Submission rule by document status, e.g. FA = PO + N weeks, FC = FA + approximately 2 months, FI = separate rule

### FA / FC / FI Handling

| Type | Meaning | Direction |
| --- | --- | --- |
| FA | First submission document | Generate range based on PO + N weeks |
| FC | Final submission after review/approval | Generate range after FA, e.g. about 2 months later |
| FI | For Information document | Requires a separate FI rule |
| Excluded | Quality, procurement, non-design documents, etc. | Filter based on customer feedback |

### Reusable Assets from Phase 1 POC

Some files from the phase 1 POC can be reused as references.

- `lts/src/features/mdl_l3_matching/validation_rule.csv`
  - Includes MDL Document Keyword, Activity Keyword, Purpose, and Validation Time. It can be used as an initial rule mapping draft.
- `lts/src/features/mdl_l3_matching/systemcode.tsv`
  - System code and system description dictionary
- `lts/src/features/mdl_l3_matching/work.tsv`
  - Work code and work description dictionary
- `lts/data/historical_fixed_data/train/*`
  - Historical L3/MDL sample data
- `data/sample_documents/.../Fadhili/Fadhili DDCL(MDL).xlsx`
  - Candidate MDL output template based on the Fadhili format

However, phase 1 POC data is based on historical project actual schedules. It should not be used directly as the official scheduling standard for the current project. It is more appropriate as **reference data and an initial mapping-rule draft**.

### Additional Information Required

The following critical materials were not clearly found in the current folders.

- Original standard CCPP Guide Schedule
- Lumanaria L2 Schedule
- Detailed L3/L4 Schedule if available
- Guide Schedule with clear Activity IDs
- Mapping table: MDL Document ↔ Activity ID ↔ Base Date ↔ PO+Week Offset
- Rules to determine FA / FC / FI target documents
- Date Range width rules
- KKS Code generation or mapping rule
- Final Excel output template

### Development Conclusion

The core function is not “schedule extraction” but a **standard-schedule-based date range generation engine**. A practical first step is to analyze `validation_rule.csv` and define an initial rule table structure, then combine it with the CCPP Guide Schedule and Activity ID mapping table provided by the customer.
