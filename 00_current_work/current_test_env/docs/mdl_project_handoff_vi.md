# Bàn Giao Dự Án MDL

## Mục Tiêu Dự Án

Mục tiêu của dự án MDL là tạo ra một Standard MDL tích hợp dựa trên các classified MDL của 7 dự án trước đó. Sau này, khi có ITB mới, hệ thống sẽ nhận diện item/package liên quan trong ITB và tự động tạo hoặc match danh sách tài liệu cần thiết.

Luồng mục tiêu hiện tại:

```text
1. Tạo integrated Standard MDL từ 7 classified MDLs
2. Trích xuất hoặc nhận diện keyword/package từ ITB và match với các section của Standard MDL
3. Bổ sung các tài liệu không được nêu trực tiếp trong ITB nhưng cần thiết theo logic package/system/equipment
```

Hiện tại đang tập trung vào bước 1: tạo Standard MDL.

## Dữ Liệu Đầu Vào Chính

Thư mục làm việc:

```text
00_current_work/current_test_env/
```

7 classified MDL input files:

```text
output/Fadhili_MDL_classified.csv
output/Grati_MDL_classified.csv
output/Karabatan_MDL_classified.csv
output/Muara Tawar_MDL_classified.csv
output/R&N_MDL_classified.csv
output/Turkistan_MDL_classified.csv
output/Ukudu_MDL_classified.csv
```

File R&N mới cập nhật:

```text
data/R&N_MDL_260612.xlsx
```

File taxonomy bắt buộc cho L1/L2:

```text
data/lv1lv2강제프롬프트.docx
```

Prompt chuyên gia CCPP:

```text
ccpp_document_classification_prompt_260423.md
```

Kết quả tham chiếu từ Doosan Copilot:

```text
output/standard_mdl/Option2 Copilot Result.xlsx
```

## Script Chính

Tạo candidate Standard MDL bằng rule-based logic:

```text
build_standard_mdl.py
```

Script LLM theo package group hiện tại:

```text
build_package_grouped_llm_pilot.py
```

Đây là script quan trọng nhất hiện tại.

Vai trò:

```text
7 classified MDLs
→ tạo source-grounded candidate bằng rule-based logic
→ lọc thành các group ACC / HRSG / DCS / EPC
→ gọi LLM theo từng group
→ merge / deduplicate / regenerate title
→ xuất Excel/CSV
```

Script tạo vendor package master candidate:

```text
build_vendor_package_master_candidate.py
```

## Quy Tắc Hiện Tại

### 1. Tách Vendor / EPC Scope

Các group đang được định nghĩa cố định:

```text
ACC Vendor Document List
HRSG Vendor Document List
DCS Vendor Document List
EPC Document List
```

Gần đây, để test, chỉ đang tạo:

```text
ACC Vendor Document List
HRSG Vendor Document List
DCS Vendor Document List
```

### 2. Bắt Buộc L1

`System (L1)` chỉ được chọn từ section 3 của file:

```text
lv1lv2강제프롬프트.docx
```

### 3. Bắt Buộc L2

`Sub-System / Area (L2)` chỉ được chọn từ:

```text
1. Equipment
2. Building
```

Nếu không match thì dùng `General`.

### 4. Không Bắt Buộc L3

Ban đầu L3 cũng bị ép theo cùng taxonomy Section 1/2. Kết quả là L2 và L3 gần như giống nhau, làm mất cấu trúc hierarchy.

Quy tắc hiện tại:

```text
L1 = forced taxonomy
L2 = forced taxonomy
L3 = LLM tự tạo concrete equipment/object dựa trên L1/L2 và source title
```

Ví dụ:

```text
L2: Air Cooled Condenser
L3: ACC Fan Motor

L2: Bypass stack
L3: Diverter Damper

L2: DCS
L3: Burner Management System
```

### 5. Quy Tắc Title

Các quy tắc title hiện tại:

```text
- Không ép Standardized Document Title thành dạng đơn giản [L3] + [Document Type]
- Loại bỏ project-specific qualifier như Block / Unit / Project / For Block 2
- Giữ nguyên title gốc trong Source Titles
- Merge các row chỉ khác nhau bởi block/unit/project qualifier
- Tách Data Sheet & Drawings thành Data Sheet và Drawing riêng
- Sử dụng abbreviation trong title: HRSG, ACC, DCS, GTG, STG, BOP, MOV, P&ID, I&C, ...
```

## Kết Quả Có Ý Nghĩa Gần Nhất

Kết quả test tốt nhất hiện tại:

```text
output/standard_mdl/package_grouped_llm_vendor_acc_hrsg_dcs_l12_forced_l3_llm/package_grouped_standard_mdl.xlsx
```

Tóm tắt kết quả:

```text
rows: 526
ACC: 106
HRSG: 357
DCS: 63
rejections: 0
invalid_l1: 0
invalid_l2: 0
L3 == L2: 9 rows
For Block / Block qualifier trong title: 0
Data Sheet & Drawings còn lại: 0
Validation Report: empty
```

Vendor package master candidate:

```text
output/standard_mdl/vendor_package_master_candidate/vendor_package_master_candidate.xlsx
```

## Các Thử Nghiệm Trước Đó

### 1. Rule-Based Integration

`build_standard_mdl.py` chạy nhanh và ổn định, nhưng nhiều title quá đơn giản: `Equipment + Document Type`. Kết quả không có cảm giác engineering-restructured như kết quả Doosan Copilot.

### 2. LLM-First Integration

Đã test R&N + Fadhili bằng cách cho LLM đọc trực tiếp raw MDL rows và tạo integrated result.

Vấn đề:

```text
- Khoảng 2 giờ cho chỉ 2 project
- Quá chậm nếu mở rộng sang 7 project
- Có rủi ro kết quả không ổn định
```

Cách tiếp cận thực tế hiện tại:

```text
rule-based candidate reduction + package-grouped LLM regeneration
```

### 3. Lỗi Khi Ép L3

Khi L3 bị ép theo cùng Section 1/2 taxonomy:

```text
L2 = HRSG
L3 = HRSG
```

Hierarchy bị mất. Hiện tại L3 do LLM tạo.

## Khác Biệt So Với Doosan Copilot

Prompt của Doosan Copilot yêu cầu mạnh hơn:

```text
- Tách Vendor / EPC hoàn toàn
- Giữ hierarchy System → Sub-System → Equipment → Document Type
- Không chỉ liệt kê tài liệu cũ
- Tái cấu trúc theo engineering logic
- Chủ động bổ sung tài liệu còn thiếu
- Tạo Foundation documents rất mạnh
```

Hiện đã phản ánh trong prompt của chúng ta:

```text
- Tách Vendor/EPC
- Merge/standardize
- Forced taxonomy cho L1/L2
- L3 concrete equipment generation
- Loại bỏ Block qualifier
- Tách Data Sheet & Drawings
- Sử dụng abbreviation
```

Còn yếu hoặc chưa implement:

```text
- Mandatory Foundation generation
- Building internal breakdown
- Mandatory Infrastructure inclusion
- Expert-Inferred missing document generation
```

## Giới Hạn Hiện Tại

Kết quả mới nhất hoàn toàn là:

```text
Evidence Type = Source-Grounded
Review Status = Approved Source-Grounded
```

Điều này có nghĩa LLM chưa tạo thêm missing documents mới.

Lý do:

```text
- Prompt hiện tại vẫn chủ yếu dựa trên source evidence
- Chưa có expected deliverable checklist theo package
- Chưa implement Expert-Inferred second pass
```

Để tạo missing documents:

```text
1. First pass: Source-Grounded merge/standardization
2. Second pass: gap analysis bằng package-level expected deliverable checklist
3. Thêm missing rows dưới dạng Expert-Inferred + Needs Doosan Review
```

## Bước Tiếp Theo Đề Xuất

1. Gửi kết quả ACC/HRSG/DCS hiện tại cho Doosan review.

Điểm cần review:

```text
- L1/L2 classification có phù hợp không?
- L3 có đủ cụ thể và có tính hierarchy không?
- Title có giống style Copilot mong muốn không?
- Có row nào bị split quá mức hoặc merge quá mức không?
- Kết quả chỉ Source-Grounded có đủ không?
```

2. Tăng cường generic title validation.

Các standalone title không hợp lệ:

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

3. Thiết kế Expert-Inferred second pass.

Thông tin cần có:

```text
- package/system/equipment hierarchy
- expected deliverable checklist theo package
- tiêu chí tách Vendor/EPC
- phạm vi cho phép tạo missing document
```

4. Mở rộng sang toàn bộ item/package section.

Hiện classified MDL + taxonomy tạo khoảng:

```text
Total section candidates: 173
Equipment-based: 106
Building-based: 49
System/Study-based: 57
General: 1
```

Không nên chạy tất cả cùng lúc. Nên ưu tiên package.

## Lệnh Chạy Hữu Ích

Chỉ tạo ACC/HRSG/DCS:

```bash
cd 00_current_work/current_test_env

.venv/bin/python build_package_grouped_llm_pilot.py \
  --all-projects \
  --batch-size 40 \
  --max-epc-batches 0 \
  --output-dir output/standard_mdl/package_grouped_llm_vendor_acc_hrsg_dcs_l12_forced_l3_llm
```

Chạy tiếp các EPC batch:

```bash
.venv/bin/python build_package_grouped_llm_pilot.py \
  --all-projects \
  --batch-size 40 \
  --epc-only \
  --epc-start-batch 21 \
  --epc-end-batch 40 \
  --output-dir output/standard_mdl/package_grouped_llm_epc_21_40
```

## Kết Luận Hiện Tại

Cấu trúc tốt nhất hiện tại là:

```text
Filter package candidates from classified MDL
→ force L1/L2 using docx taxonomy
→ let LLM generate L3 as concrete equipment/object
→ LLM merges, deduplicates, and regenerates titles per package
→ post-process block/unit removal, composite deliverable split, validation
→ Doosan review and confirmation
```
