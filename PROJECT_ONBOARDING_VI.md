# Tài liệu onboarding dự án Doosan MDL

Tài liệu này dành cho lập trình viên chưa có kiến thức trước về repository. Mục tiêu là giúp nắm nhanh dự án này làm gì, dữ liệu đi qua những bước nào, cấu trúc thư mục ra sao, kết quả hiện tại là gì, và các bước tiếp theo cần triển khai.

## 1. Tóm tắt một dòng

Dự án này là workspace thử nghiệm/kiểm chứng để tự động tạo hoặc match danh sách Master Document List (MDL) cho dự án nhà máy điện, dựa trên tài liệu ITB và dữ liệu MDL của các dự án quá khứ.

Luồng công việc chính hiện tại:

```text
MDL Excel của các dự án cũ
  -> phân loại bằng AI/rule
  -> tạo classified MDL CSV cho 7 dự án
  -> tích hợp classified MDL thành ứng viên Standard MDL
  -> tái cấu trúc bằng LLM theo Vendor/EPC và Package/Scope
  -> match Standard MDL với L3/Guide Schedule Activity
  -> tạo FA / FC / FI submission Date Range
  -> xuất Excel/CSV để kỹ sư review
```

## 2. Vấn đề dự án giải quyết

Khi bắt đầu một dự án nhà máy, đội kỹ thuật phải đọc ITB, hợp đồng, specification và các tài liệu liên quan để xác định những tài liệu thiết kế/mua sắm/xây dựng cần nộp. Kết quả là MDL.

Cách làm thủ công mất nhiều thời gian, phụ thuộc kinh nghiệm từng người, và dễ phát sinh thiếu sót hoặc trùng lặp. Dự án này hướng tới:

- Chuẩn hóa MDL của các dự án quá khứ.
- Tự động đề xuất danh sách tài liệu theo ITB hoặc package keyword.
- Tách Vendor Document List và EPC Document List.
- Phân biệt kết quả có nguồn gốc rõ ràng từ dữ liệu cũ với kết quả cần Doosan review.
- Xuất kết quả ở dạng Excel/CSV có thể kiểm tra.

## 3. Thuật ngữ chính

| Thuật ngữ | Ý nghĩa |
| --- | --- |
| ITB | Invitation To Bid. Tài liệu yêu cầu thầu/hợp đồng do chủ đầu tư cung cấp. |
| MDL | Master Document List. Danh sách tài liệu cần nộp trong dự án. |
| Classified MDL | CSV trong đó từng dòng MDL gốc được phân loại theo Equipment, Building, System, Deliverable, v.v. |
| Standard MDL | Danh sách tài liệu chuẩn hóa, được tích hợp từ classified MDL của nhiều dự án. |
| Vendor Document List | Danh sách tài liệu theo vendor package như ACC, HRSG, DCS, Pump. |
| EPC Document List | Danh sách tài liệu thuộc phạm vi EPC. |
| Work Component | Đối tượng mà tài liệu nói đến: equipment, system, building, package. |
| Deliverable | Loại tài liệu như Drawing, Data Sheet, Calculation, Manual. |
| L1/L2/L3 | Cấp phân cấp trong Standard MDL. Hiện tại L1/L2 bị ràng buộc bởi taxonomy, còn L3 do LLM tạo thành tên thiết bị/đối tượng cụ thể hơn. |
| Level 3 Schedule (L3) | Lịch tiến độ chi tiết của dự án. Không được nhầm với Equipment (L3) trong taxonomy MDL. |
| FA | First Approval hoặc mốc nộp/duyệt đầu tiên. |
| FC | Final Comment hoặc mốc comment/duyệt cuối. |
| FI | For Information. Loại tài liệu nộp để thông tin. |
| NTP | Notice To Proceed. Mốc bắt đầu dự án, từng được legacy POC dùng làm base date. |
| Trimmed ID | Mã định danh Activity trong L3 Schedule. Legacy dùng mã này để trích System Code và Work Code. |
| Source-Grounded | Kết quả có căn cứ trực tiếp từ dòng MDL quá khứ. |
| Expert-Inferred / Needs Doosan Review | Kết quả có tính suy luận/bổ sung, cần Doosan review. |

## 4. Vị trí quan trọng trong repository

Repository này chứa cả code thử nghiệm, dữ liệu mẫu, tài liệu tham khảo và legacy POC. Điểm phát triển chính hiện tại là:

```text
00_current_work/current_test_env/
```

| Đường dẫn | Vai trò |
| --- | --- |
| `00_current_work/current_test_env/` | Môi trường test hiện tại, gồm script, prompt, dữ liệu vào và output. |
| `00_current_work/current_test_env/mdl_runtime/` | Helper runtime: config, Neo4j connection, Azure OpenAI embedding. |
| `00_current_work/current_test_env/data/` | MDL Excel, abbreviation, taxonomy docx, ITB chunk JSON dùng trong test hiện tại. |
| `00_current_work/current_test_env/output/` | Classified MDL và Standard MDL output. |
| `00_current_work/current_test_env/docs/` | Tài liệu handoff/checklist của công việc hiện tại. |
| `03_reference_docs/` | Proposal, prompt feedback từ Doosan, system notes, vendor reference docs. |
| `04_data/` | Tài liệu nguồn/mẫu theo dự án. |
| `output/` | Một số kết quả validation/matching riêng ở root. |
| `src/` | Hiện không phải active source. Chủ yếu là package metadata/generated cache. |
| `.codex/FIX_LOG.md` | Log công việc local. Bị Git ignore, dùng cho handoff nội bộ. |

## 5. Cấu trúc môi trường test hiện tại

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

Các script quan trọng:

| File | Vai trò |
| --- | --- |
| `classify_mdl_v5-2.py` | Đọc MDL Excel và dùng prompt AI để phân loại từng dòng theo Equipment, Building, System, Study/Survey, Others, Deliverable. |
| `build_standard_mdl.py` | Tích hợp 7 classified MDL CSV thành ứng viên Standard MDL có audit, validation, rejection. |
| `build_package_grouped_llm_pilot.py` | Script quan trọng nhất hiện tại. Giảm ứng viên theo package/scope rồi dùng LLM để merge, chuẩn hóa và bổ sung. |
| `build_vendor_package_master_candidate.py` | Tổng hợp Equipment từ classified MDL để tạo vendor package master candidate và danh sách cần review. |

## 6. Dữ liệu đầu vào chính

### 6.1 MDL Excel gốc

Nằm trong:

```text
00_current_work/current_test_env/data/
```

Ví dụ:

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

### 6.2 Classified MDL

Đây là input trực tiếp cho Standard MDL generation.

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

Luồng chính trong `build_standard_mdl.py` dùng 7 dự án:

```text
Fadhili, Grati, Karabatan, Muara Tawar, R&N, Turkistan, Ukudu
```

### 6.3 Prompt và taxonomy

| File | Vai trò |
| --- | --- |
| `00_current_work/current_test_env/ccpp_document_classification_prompt_260423.md` | Prompt chuyên gia CCPP cho phân loại/chuẩn hóa tài liệu. |
| `00_current_work/current_test_env/data/lv1lv2강제프롬프트.docx` | Nguồn taxonomy bắt buộc cho L1/L2. |
| `03_reference_docs/prompt_feedback/` | Prompt document dựa trên feedback của Doosan. |
| `03_reference_docs/6개기준 분류 프롬프트(Doosan Feedback)_20260521.docx` | Tài liệu tham khảo cho tiêu chí phân loại mới hơn. |

### 6.4 Dữ liệu ITB

Repository có ITB chunk JSON và tài liệu nguồn:

```text
00_current_work/current_test_env/data/itb_chunks/
04_data/sample_documents/project_samples/
```

Tuy nhiên trọng tâm hiện tại không phải chạy full ITB pipeline, mà là tạo Standard MDL/package list từ classified MDL.

## 7. Luồng xử lý tổng thể

### 7.1 Bước 1: Phân loại MDL

```text
MDL Excel gốc
  -> classify_mdl_v5-2.py
  -> gọi Azure OpenAI chat model
  -> *_MDL_classified.csv
```

Các cột output tiêu biểu:

```text
Source File, Sheet, Document No, Title,
Equipment, Building, System, Study/Survey, Others,
Deliverable, Note
```

### 7.2 Bước 2: Tạo ứng viên Standard MDL bằng rule

```text
7 classified MDL CSV
  -> build_standard_mdl.py
  -> tạo source-grounded candidate
  -> tách Vendor/EPC scope
  -> xuất audit / validation / rejection
```

Ưu điểm:

- Nhanh và có tính lặp lại.
- Giữ được source traceability.

Hạn chế:

- Kết quả có thể máy móc.
- Chưa đủ mạnh để tái cấu trúc theo góc nhìn engineering như output của Copilot.

### 7.3 Bước 3: Chuẩn hóa bằng LLM theo package/group

```text
Rule-based candidate
  -> lọc theo package/scope group
  -> LLM merge/standardize/supplement theo từng group
  -> xuất Excel/CSV
```

Lý do chọn cách này:

- Nếu cho LLM xử lý toàn bộ MDL một lần sẽ chậm, tốn chi phí và dễ dao động.
- Rule giúp thu hẹp candidate và giữ source grounding.
- Package-level processing giúp tạo list theo engineering package như ACC, HRSG, DCS, Pump.

### 7.4 Bước 4: Tạo vendor package master candidate

```text
classified MDL Equipment column
  -> build_vendor_package_master_candidate.py
  -> canonical package mapping
  -> mapped / review-needed list
```

Output này dùng để quyết định package section nào cần chạy tiếp.

### 7.5 Bước 5: Tạo lịch MDL dựa trên L3/Guide Schedule

Sau khi tạo Standard MDL hoặc package integrated MDL, cần gắn thông tin lịch nộp cho từng tài liệu. Ở đây L3 là **Level 3 Schedule**, không phải `Equipment (L3)` trong MDL taxonomy.

Luồng mục tiêu:

```text
Standard MDL / Package Integrated MDL
  -> match với CCPP Guide Schedule hoặc project L3 Schedule Activity
  -> chọn Activity base date
     ví dụ: PO Finish, NTP, ICOD, PCOD
  -> áp dụng rule nộp theo document status/type
     ví dụ: FA = PO + N tuần, FC = FA + khoảng 2 tháng, FI = rule riêng
  -> tạo FA / FC / FI Date Range, không chỉ một ngày đơn lẻ
  -> người dùng chọn ngày thực tế trong range
  -> xuất MDL Excel có lịch
```

Chức năng này nên được hiểu là **engine tạo date range dựa trên schedule chuẩn**, không phải chỉ là trích xuất lịch.

Legacy POC có code liên quan ở:

```text
01_legacy_poc/master-document-list-project-main/lts/
```

Có hai nhóm chức năng chính.

```text
1. Dự đoán ngày FA/FC dựa trên lịch thực tế quá khứ
2. Match MDL document với L3 Activity và validate lịch
```

Nhóm 1 nằm trong:

```text
src/features/date_generation/basic/hybrid_search.py
src/features/date_generation/basic/keyword_search.py
src/features/date_generation/basic/semantic_search.py
src/features/date_generation/advanced/lightgbm_model.py
src/features/preprocessing/preprocess.py
```

Legacy dùng MDL + L3 Schedule của dự án quá khứ để tạo các offset như `NTP_to_FA`, `FA_to_FC`, `NTP_to_FC`. Sau đó dùng BM25 + embedding hybrid search để tìm tài liệu quá khứ tương tự với tài liệu mới, rồi dự đoán FA/FC bằng weighted average. Nếu không có tài liệu tương tự, hệ thống dùng LightGBM model làm fallback.

Cách này chỉ nên dùng để tham khảo. Không nên dùng trực tiếp làm chuẩn chính thức cho phase 2, vì lịch thực tế quá khứ có thể chứa yếu tố không chuẩn như chậm tiến độ, khác biệt chủ đầu tư, COVID, chiến tranh, bão, v.v.

Nhóm 2 nằm trong:

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

Nhóm này có giá trị tái sử dụng trực tiếp hơn:

- Parse MDL title để lấy item và document name.
- Trích item từ L3 WBS hierarchy.
- Match MDL document với L3 Activity bằng semantic search.
- Với dòng không match, dùng System Code / Work Code từ `Trimmed ID` để fallback.
- Dùng rule trong `validation_rule.csv` để so sánh Activity `Start`/`Finish` với MDL `FA`/`FC`.
- Phân loại kết quả thành `Valid`, `Extended Valid`, `Under`, `Over`, `Unmatch`.

`validation_rule.csv` là rule table có ý nghĩa như sau:

```text
MDL Document Keyword
  -> Activity Keyword
  -> Purpose(FA/FC/FI...)
  -> Date_choice(Max/Min...)
  -> Validation Time
```

Ví dụ:

```text
MDL Document Keyword: P&ID for Water Treatment System
Activity Keyword: P.O
Purpose: FA
Date_choice: Max
Validation Time: start+1M<=FA<=start+1M+2M
```

Nghĩa là tài liệu đó dùng Activity có keyword `P.O` làm mốc, và FA phải nằm trong range từ `start + 1 tháng` đến `start + 3 tháng`.

Hướng áp dụng cho phase 2:

| Thành phần legacy | Hướng xử lý |
| --- | --- |
| Dự đoán FA/FC bằng lịch thực tế quá khứ | Không dùng trực tiếp; chỉ tham khảo. |
| `validation_rule.csv` | Có thể dùng làm bản nháp rule table dựa trên CCPP Guide Schedule. |
| `systemcode.tsv`, `work.edited.tsv` | Có thể dùng làm dictionary giải mã Activity ID/Trimmed ID. |
| `new_rules` matching pipeline | Có thể tham khảo cấu trúc semantic matching + system code fallback. |
| `assign_label.py` | Có giá trị tái sử dụng để parse expression như `start+1M<=FA<=start+3M`. |

Các tài liệu cần bổ sung/xác nhận:

```text
- CCPP Guide Schedule chuẩn
- Guide Schedule có Activity ID rõ ràng
- Lumanaria L2 Schedule hoặc project L3/L4 Schedule thực tế
- Mapping table: MDL document ↔ Activity ID ↔ base date ↔ PO+Week Offset
- Rule xác định tài liệu nào là FA / FC / FI
- Quy tắc độ rộng Date Range
- Rule chọn base date: PO Finish, NTP, ICOD, PCOD
- Template Excel output cuối cùng có lịch
```

## 8. Rule chính đang dùng

### 8.1 Tách Vendor / EPC scope

Scope chính:

```text
Vendor
EPC
```

Vendor được chia theo package:

```text
ACC Vendor Document List
HRSG Vendor Document List
DCS Vendor Document List
Pump Vendor Document List
ST/STG Vendor Document List
...
```

### 8.2 Bắt buộc L1/L2 taxonomy

`data/lv1lv2강제프롬프트.docx` là nguồn taxonomy.

- `System (L1)` chỉ chọn trong system taxonomy.
- `Sub-System / Area (L2)` chỉ chọn trong Equipment/Building list.
- Nếu không có giá trị phù hợp thì có thể dùng `General`.

### 8.3 Không bắt buộc L3 taxonomy

Ban đầu L3 cũng bị ép theo taxonomy, nhưng dẫn đến lỗi phân cấp:

```text
L2 = HRSG
L3 = HRSG
```

Hướng hiện tại:

```text
L1 = forced taxonomy
L2 = forced taxonomy
L3 = LLM tạo tên equipment/object cụ thể dựa trên source title và L1/L2
```

Ví dụ:

```text
L2: Air Cooled Condenser
L3: ACC Fan Motor

L2: HRSG
L3: Diverter Damper

L2: DCS
L3: Burner Management System
```

### 8.4 Rule chuẩn hóa title

- Không ép `Standardized Document Title` thành `[L3] + [Document Type]` một cách máy móc.
- Loại bỏ qualifier theo dự án như `Block`, `Unit`, `Project`, `For Block 2`.
- Giữ nguyên title gốc trong `Source Titles`.
- Merge các tài liệu giống nhau chỉ khác block/unit.
- Tách `Data Sheet & Drawings` thành `Data Sheet` và `Drawing`.
- Cho phép abbreviation quen thuộc trong ngành.

Abbreviation tiêu biểu:

```text
HRSG, ACC, DCS, GTG, STG, BOP, MOV, P&ID, I&C, MV, LV, UPS
```

## 9. Output và trạng thái hiện tại

### 9.1 Vendor ACC/HRSG/DCS package-grouped

```text
00_current_work/current_test_env/output/standard_mdl/
  package_grouped_llm_vendor_acc_hrsg_dcs_l12_forced_l3_free/
    package_grouped_standard_mdl.xlsx
    package_grouped_standard_mdl.csv
    package_grouped_audit.csv
    package_grouped_rejections.csv
    package_grouped_validation.csv
```

CSV hiện tại:

```text
package_grouped_standard_mdl.csv: 437 data rows
```

Các cột chính:

```text
No, Section, Package/Scope Group, Discipline, Document Type,
System (L1), Sub-System / Area (L2), Equipment (L3),
Standardized Document Title, Scope, Evidence Type, Review Status,
Source Standard Nos, Source Projects, Source Document Nos,
Source Titles, Generation / Merge Reason
```

### 9.2 EPC package-grouped

```text
00_current_work/current_test_env/output/standard_mdl/
  package_grouped_llm_epc_l12_forced_l3_free/
    epc_grouped_standard_mdl.xlsx
    package_grouped_standard_mdl.csv
    package_grouped_audit.csv
    package_grouped_rejections.csv
    package_grouped_validation.csv
```

CSV hiện tại:

```text
package_grouped_standard_mdl.csv: 4340 data rows
```

### 9.3 Item-level vendor package

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

CSV hiện tại:

```text
pump_integrated_mdl_list.csv: 503 data rows
st_stg_integrated_mdl_list.csv: 313 data rows
```

Theo work log, kết quả Pump:

```text
source_rows: 1117
candidate_rows: 470
output_rows: 503
rejections: 0
Approved Source-Grounded: 474
Needs Doosan Review: 29
```

### 9.4 Vendor package master candidate

```text
00_current_work/current_test_env/output/standard_mdl/
  vendor_package_master_candidate/
    vendor_package_master_candidate.xlsx
    vendor_package_master_candidate.csv
    vendor_package_master_review_needed.csv
    vendor_package_master_candidate_260618_DoosanFeedback.xlsx
```

CSV hiện tại:

```text
vendor_package_master_candidate.csv: 735 data rows
vendor_package_master_review_needed.csv: 229 data rows
```

### 9.5 Rule-based Standard MDL

```text
00_current_work/current_test_env/output/standard_mdl/
  validation_report.csv
  rejections.csv
  source_mapping_audit.csv
```

Đây là output kiểm chứng/traceability của `build_standard_mdl.py`.

## 10. Những gì đã làm đến hiện tại

1. Đã chuyển MDL của 7 dự án thành classified CSV.
2. Đã tạo ứng viên Standard MDL bằng rule từ 7 classified MDL.
3. Đã xác nhận rule-only nhanh nhưng chưa đủ mạnh về engineering reconstruction.
4. Đã thử/đánh giá hướng LLM-first và thấy không phù hợp để mở rộng toàn bộ 7 dự án.
5. Đã chuyển sang hướng `rule-based candidate reduction + package/group LLM reconstruction`.
6. Đã tạo kết quả vendor package ACC/HRSG/DCS.
7. Đã tạo kết quả EPC riêng.
8. Đã tạo item-level vendor result cho ST/STG và Pump.
9. Đã tạo vendor package master candidate để xác định package tiếp theo.
10. Đã xác nhận sau bước Standard MDL cần thêm chức năng tạo FA/FC/FI Date Range dựa trên L3/Guide Schedule.
11. Đã phân tích legacy POC: phần dự đoán lịch quá khứ chỉ nên tham khảo, còn validation rule và matching structure là ứng viên tái sử dụng.

## 11. Bài học từ các thử nghiệm trước

### 11.1 Rule-only

Ưu điểm:

- Nhanh.
- Có tính lặp lại.
- Dễ trace source title/document no.

Hạn chế:

- Kết quả giống gom/chuẩn hóa title hơn là engineering standard list.
- So với output kiểu Copilot thì yếu hơn về cấu trúc engineering.

### 11.2 LLM-first

Ưu điểm:

- Kết quả tự nhiên hơn và giống engineering list hơn.

Hạn chế:

- Chậm và tốn chi phí.
- Khó mở rộng từ 2 dự án lên 7 dự án.
- Source grounding khó kiểm chứng.

### 11.3 Hướng hiện tại

Hướng thực tế nhất:

```text
Rule-based candidate reduction
  + Package/Scope grouping
  + LLM standardization
  + Source-grounding validation
  + Doosan review flagging
```

## 12. Cách chạy

Chạy lệnh từ:

```bash
cd 00_current_work/current_test_env
```

### 12.1 Chuẩn bị môi trường

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Nếu có `uv`:

```bash
uv pip install -r requirements.txt
```

Yêu cầu chính:

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

### 12.2 Environment variables

Copy `.env.example` thành `.env` và điền giá trị.

Các biến chính:

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

`mdl_runtime/config.py` hiện có default chat deployment là `gpt-5.2`.

### 12.3 Tạo Classified MDL

```bash
python classify_mdl_v5-2.py
```

Lưu ý:

- Cần Azure OpenAI API key.
- Nên chạy từ `current_test_env` vì script phụ thuộc relative path.

### 12.4 Tạo rule-based Standard MDL

```bash
python build_standard_mdl.py
```

Output:

```text
output/standard_mdl/
  validation_report.csv
  rejections.csv
  source_mapping_audit.csv
```

### 12.5 Tạo package-grouped LLM result

Ví dụ:

```bash
python build_package_grouped_llm_pilot.py --all-projects --vendor-section-title "Pump Vendor Document List"
```

Kết quả Pump đã có ở:

```text
output/standard_mdl/item_level_runs/pump/
```

### 12.6 Tạo vendor package master candidate

```bash
python build_vendor_package_master_candidate.py
```

Output:

```text
output/standard_mdl/vendor_package_master_candidate/
  vendor_package_master_candidate.xlsx
  vendor_package_master_candidate.csv
  vendor_package_master_review_needed.csv
```

## 13. Cấu trúc phát triển và nguyên tắc code

Hiện repository là workspace thử nghiệm/script-based, chưa phải application package hoàn chỉnh.

- Script nằm ở root của `current_test_env`.
- Logic dùng chung nằm trong `mdl_runtime/`.
- Input/output phụ thuộc relative path.
- Vị trí chạy script rất quan trọng.

Khi thêm code mới:

- Đưa logic tái sử dụng vào `mdl_runtime/`.
- Giữ workflow-specific logic trong script riêng.
- Output path phải rõ ràng.
- Giữ source traceability columns.
- Validate LLM output bằng source id/document no khi có thể.
- Ưu tiên test pure logic không phụ thuộc live Azure OpenAI/Neo4j.

Không nên:

- Sửa `src/doosan_mdl.egg-info` như active source.
- Commit `.env`, `.venv`, `__pycache__`, bulk generated data nếu không có yêu cầu.
- Copy dữ liệu khách hàng nhạy cảm không cần thiết.

## 14. Góc nhìn validation

Khi review output, không chỉ nhìn số dòng. Cần kiểm tra:

- `rejections.csv` có rỗng không, hoặc lý do rejection có hợp lý không.
- `validation.csv` / `validation_report.csv` có invalid L1/L2 hoặc title issue không.
- `Source Standard Nos`, `Source Document Nos`, `Source Titles` có trace được về input không.
- `Evidence Type` có phân biệt đúng source-grounded và expert-inferred không.
- `Review Status` có giữ rõ các dòng cần Doosan review không.
- `Data Sheet & Drawings` đã được tách chưa.
- Qualifier như `Block`, `Unit`, `Project` có còn trong title không.
- L2 và L3 có bị trùng quá nhiều làm mất phân cấp không.

## 15. Tài liệu nên đọc

Thứ tự khuyến nghị:

1. Tài liệu này: `PROJECT_ONBOARDING_VI.md`
2. Bản tiếng Hàn: `PROJECT_ONBOARDING_KO.md`
3. README môi trường test: `00_current_work/current_test_env/README.md`
4. Handoff tiếng Hàn: `00_current_work/current_test_env/docs/mdl_project_handoff_ko.md`
5. Cấu trúc folder: `FOLDER_STRUCTURE.md`
6. System overview: `03_reference_docs/system_notes/mdl_system_overview.md`
7. Comprehensive guide: `03_reference_docs/system_notes/mdl_system_comprehensive_guide.md`
8. Work log: `.codex/FIX_LOG.md`

## 16. Việc tiếp theo

- Review `vendor_package_master_review_needed.csv` và bổ sung package mapping rule.
- Chạy package tiếp theo sau Pump, ví dụ Electrical Equipment hoặc GT/GTG tùy checklist mới nhất.
- So sánh validation/rejection của ACC/HRSG/DCS, EPC, ST/STG, Pump.
- Thiết kế bước tạo lịch dựa trên L3/Guide Schedule sau Standard MDL.
- Quyết định phạm vi porting từ legacy: `validation_rule.csv`, `systemcode.tsv`, `work.edited.tsv`, `new_rules` matching pipeline.
- Yêu cầu khách hàng cung cấp CCPP Guide Schedule, mapping MDL document ↔ Activity ID ↔ base date ↔ offset.
- Xác định rule tạo FA / FC / FI Date Range và final Excel template.
- Thêm post-processing rule cho trường hợp L3 giống L2 hoặc quá generic.
- Cập nhật README cho option/output naming của `build_package_grouped_llm_pilot.py`.
- Thêm smoke test không cần live LLM để giảm regression.

## 17. Những điểm cần nhớ ngay

- Folder làm việc chính là `00_current_work/current_test_env/`.
- Trọng tâm hiện tại là tạo Standard MDL/package list từ classified MDL, không phải full ITB pipeline.
- Script quan trọng nhất hiện tại là `build_package_grouped_llm_pilot.py`.
- Chất lượng output phụ thuộc vào source grounding, tuân thủ L1/L2 taxonomy, độ cụ thể của L3, và chuẩn hóa title.
- Sau Standard MDL cần thêm bước tạo FA/FC/FI Date Range dựa trên Level 3 Schedule.
- Trong phần schedule, L3 nghĩa là Level 3 Schedule, không phải Equipment (L3) trong MDL taxonomy.
- Output luôn cần kỹ sư review; không được ẩn các dòng `Needs Doosan Review`.
- Khi thay đổi code, prompt, workflow, output, validation hoặc execution behavior, phải ghi vào `.codex/FIX_LOG.md`.
