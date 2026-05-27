"""
CCPP MDL Document Title Classification Script (v6 - Structured Output)

주요 변경사항 (v5-2 → v6):
  1. CSV 파싱 제거 → Pydantic Structured Output 사용
     · 내부 쉼표(예: "Building - 11, 12, 13") 문제 원천 차단
     · 필드 누락/타입 불일치 가능성 제거
  2. 하이브리드 프롬프트 사용 (260417 hybrid)
  3. AzureOpenAI 클라이언트 재사용 (호출마다 재생성 안 함)
  4. API 키는 .env 또는 환경변수에서 로드
  5. 배치 응답 길이 검증 강화

사용법:
  export AZURE_OPENAI_API_KEY="..."   # 권장
  python3 classify_mdl_v6.py                       # 전체 파일 처리
  python3 classify_mdl_v6.py Fadhili_MDL.xlsx      # 특정 파일만
"""

import os
import sys
import csv
import time
import openpyxl
from tqdm import tqdm
from pydantic import BaseModel, Field
from openai import AzureOpenAI

from mdl_runtime.config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_CHAT_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    DATA_DIR,
    OUTPUT_DIR,
    required,
)

# ── Azure OpenAI 설정 ──────────────────────────────────────────
# ⚠️  API 키 보안: 가능하면 환경변수 사용을 권장합니다.
#     export AZURE_OPENAI_API_KEY="..."
#     소스에 하드코딩된 키는 git 등으로 유출 시 즉시 폐기하세요.
AZURE_ENDPOINT = AZURE_OPENAI_ENDPOINT
API_KEY = AZURE_OPENAI_API_KEY
API_VERSION = AZURE_OPENAI_CHAT_API_VERSION
MODEL_DEPLOYMENT = AZURE_OPENAI_CHAT_DEPLOYMENT

# ── 파일 경로 ─────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.getenv(
    "PROMPT_FILE",
    os.path.join(SCRIPT_DIR, "ccpp_document_classification_prompt_260423.md"),
)
DATA_DIR = str(DATA_DIR)
OUTPUT_DIR = str(OUTPUT_DIR)

# ── 배치 크기 ─────────────────────────────────────────────────
BATCH_SIZE = 20


# ─────────────────────────────────────────────────────────────
# Pydantic 응답 스키마
# ─────────────────────────────────────────────────────────────
class DocumentClassification(BaseModel):
    """단일 문서 분류 결과."""
    equipment: str = Field(
        description="Equipment scope (e.g., HRSG, ACC, GT, Pump). Empty string if none applies."
    )
    building: str = Field(
        description="Building or facility scope (e.g., Control Building, Pipe Rack). Empty string if none applies."
    )
    system: str = Field(
        description="System scope (e.g., Fuel Gas System, HVAC). Empty string if none applies."
    )
    study_survey: str = Field(
        description="Study/survey scope (e.g., HAZOP Study, Soil Investigation, Load Flow Study). Empty string if none applies."
    )
    others: str = Field(
        description="Other specific technical subjects, target objects, or engineering scopes not covered by equipment, building, system, or study/survey. May contain commas, slashes, or special chars. Empty string if none applies."
    )
    deliverable: str = Field(
        description="Document type or engineering output (e.g., P&ID, Datasheet, Sizing Calculation, Architectural Drawing)."
    )


class BatchClassification(BaseModel):
    """배치 분류 결과 (입력 순서 유지)."""
    results: list[DocumentClassification]


# ─────────────────────────────────────────────────────────────
# 프롬프트 로드
# ─────────────────────────────────────────────────────────────
def load_system_prompt(path: str) -> str:
    """프롬프트 파일 로드. CSV 출력 모드는 무시하고 Structured Output 모드 안내 추가."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Input Template 섹션 제거
    idx = content.rfind("## Input Template")
    if idx != -1:
        content = content[:idx].rstrip()

    # Structured output override (CSV 관련 규칙 무력화)
    content += (
        "\n\n---\n\n"
        "## Output Mode (OVERRIDE — IMPORTANT)\n\n"
        "Ignore any CSV-related output rules above. "
        "Return your answer as a structured object with these fields per description:\n"
        "  - `equipment` (string, may be empty)\n"
        "  - `building` (string, may be empty)\n"
        "  - `system` (string, may be empty)\n"
        "  - `study_survey` (string, may be empty)\n"
        "  - `others` (string, may contain commas, slashes, parentheses)\n"
        "  - `deliverable` (string)\n\n"
        "For batch input (multiple numbered descriptions), return ONE object per description "
        "in the SAME ORDER as input, wrapped in the `results` array. "
        "The number of results MUST equal the number of input descriptions.\n\n"
        "Internal commas in any field are now SAFE — keep them as-is. "
        "Example: a building name like \"Unit MV/LV Switchgear Building - 11, 12, 13\" "
        "should be placed in `building` or `others` exactly as written, including the commas. "
        "Map the prompt's `Study/Survey` field to `study_survey`."
    )
    return content


# ─────────────────────────────────────────────────────────────
# Excel 추출 (기존 로직 유지)
# ─────────────────────────────────────────────────────────────
def extract_titles_from_excel(filepath: str) -> list[dict]:
    """엑셀 파일에서 Title/Description 열을 추출."""
    filename = os.path.basename(filepath)
    results = []

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        title_col = None
        docno_col = None
        header_row_idx = None

        for i, row in enumerate(rows[:10]):
            for j, cell in enumerate(row):
                if cell is None:
                    continue
                cell_str = str(cell).strip().upper()
                if cell_str in ("TITLE", "DOCUMENT DESCRIPTION", "DOCUMENT TITLE"):
                    title_col = j
                    header_row_idx = i
                if cell_str in ("DOCUMENT NUMBER", "DOCUMENT NO", "DOCUMENT NO.", "DOC NO"):
                    docno_col = j
            if title_col is not None:
                break

        if title_col is None:
            continue

        for row in rows[header_row_idx + 1:]:
            if title_col >= len(row):
                continue
            title_val = row[title_col]
            if title_val is None or str(title_val).strip() == "":
                continue
            title_str = str(title_val).strip()

            if title_str.upper() in ("TITLE", "DOCUMENT DESCRIPTION", "DOCUMENT TITLE"):
                continue

            doc_no = ""
            if docno_col is not None and docno_col < len(row) and row[docno_col] is not None:
                doc_no = str(row[docno_col]).strip()

            results.append({
                "source": filename,
                "sheet": sheet_name,
                "doc_no": doc_no,
                "title": title_str,
            })

    wb.close()
    return results


# ─────────────────────────────────────────────────────────────
# Structured Output 호출
# ─────────────────────────────────────────────────────────────
def classify_batch(
    client: AzureOpenAI,
    system_prompt: str,
    titles: list[str],
    max_retries: int = 3,
) -> list[tuple[str, str, str, str, str, str, str]]:
    """
    배치 분류. (equipment, building, system, study_survey, others, deliverable, note) 튜플 리스트 반환.
    Structured Output을 사용하므로 CSV 파싱이 필요 없음.
    """
    if len(titles) == 1:
        user_msg = f'Description = "{titles[0]}"'
    else:
        lines = [f'{i}. Description = "{t}"' for i, t in enumerate(titles, 1)]
        user_msg = (
            f"Classify the following {len(titles)} descriptions. "
            f"Return exactly {len(titles)} objects in the `results` array, "
            f"in the SAME ORDER as input.\n\n"
            + "\n".join(lines)
        )

    last_error = ""
    for attempt in range(max_retries):
        try:
            # 신버전 SDK는 client.chat.completions.parse, 구버전은 client.beta.chat.completions.parse
            try:
                response = client.chat.completions.parse(
                    model=MODEL_DEPLOYMENT,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    response_format=BatchClassification,
                    temperature=0.0,
                    max_completion_tokens=16384,
                )
            except AttributeError:
                response = client.beta.chat.completions.parse(
                    model=MODEL_DEPLOYMENT,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    response_format=BatchClassification,
                    temperature=0.0,
                    max_completion_tokens=16384,
                )

            msg = response.choices[0].message
            parsed: BatchClassification | None = msg.parsed

            # Refusal 체크
            if parsed is None:
                refusal = getattr(msg, "refusal", None) or "no parsed result"
                last_error = f"Parse failed: {refusal}"
                print(f"  [WARN] {last_error}")
                break

            # 결과 변환
            results = [
                (
                    r.equipment.strip(),
                    r.building.strip(),
                    r.system.strip(),
                    r.study_survey.strip(),
                    r.others.strip(),
                    r.deliverable.strip(),
                    "",
                )
                for r in parsed.results
            ]

            # 결과 개수 검증 (모델이 누락한 경우)
            if len(results) < len(titles):
                missing = len(titles) - len(results)
                print(f"  [WARN] Model returned {len(results)} but expected {len(titles)}. "
                      f"Padding {missing} empty rows.")
                results.extend([("", "", "", "", "", "", "missing from batch response")] * missing)
            elif len(results) > len(titles):
                print(f"  [WARN] Model returned {len(results)} but expected {len(titles)}. Truncating.")
                results = results[:len(titles)]

            return results

        except Exception as e:
            err_msg = str(e)
            err_type = type(e).__name__
            last_error = f"{err_type}: {err_msg}"
            print(f"  Error attempt {attempt+1}/{max_retries}: {err_msg[:200]}")

            if "429" in err_msg or "RateLimit" in err_type:
                wait = 2 ** (attempt + 2)
                print(f"  Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            elif "400" in err_msg or "content_filter" in err_msg.lower() or "BadRequest" in err_type:
                print("  [SKIP] Content filter or bad request. Returning empty.")
                return [("", "", "", "", "", "", err_msg[:200])] * len(titles)
            elif attempt < max_retries - 1:
                time.sleep(2)
            else:
                break

    return [("", "", "", "", "", "", last_error[:200])] * len(titles)


# ─────────────────────────────────────────────────────────────
# 파일 단위 처리
# ─────────────────────────────────────────────────────────────
def classify_file(client: AzureOpenAI, system_prompt: str, filepath: str, output_path: str):
    """단일 엑셀 파일 처리 → 개별 CSV 생성."""
    filename = os.path.basename(filepath)
    print(f"\n{'─' * 50}")
    print(f"[FILE] {filename}")

    records = extract_titles_from_excel(filepath)
    print(f"  Extracted: {len(records)} titles")
    # records = records[:100]  # 요청에 의해 100개행만 테스트
    # print(f"  Extracted: {len(records)} titles (Limited to 100)")

    if not records:
        print("  No titles found. Skipping.")
        return

    classified = []
    total_batches = (len(records) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in tqdm(range(total_batches), desc="  Classifying", unit="batch"):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(records))
        batch_records = records[start:end]
        batch_titles = [r["title"] for r in batch_records]

        results = classify_batch(client, system_prompt, batch_titles)

        for rec, (eq, bld, system_scope, study_survey, oth, deliv, note) in zip(batch_records, results):
            classified.append({
                "Source File": rec["source"],
                "Sheet": rec["sheet"],
                "Document No": rec["doc_no"],
                "Title": rec["title"],
                "Equipment": eq,
                "Building": bld,
                "System": system_scope,
                "Study/Survey": study_survey,
                "Others": oth,
                "Deliverable": deliv,
                "Note": note,
            })

        if batch_idx < total_batches - 1:
            time.sleep(1)

    # CSV 저장 (csv 모듈이 내부 쉼표를 자동 escape 처리)
    fieldnames = ["Source File", "Sheet", "Document No", "Title",
                  "Equipment", "Building", "System", "Study/Survey", "Others", "Deliverable", "Note"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(classified)

    print(f"  [SAVED] {output_path} ({len(classified)} rows)")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("CCPP MDL Document Title Classification (v6 - Structured Output)")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 시스템 프롬프트 로드
    if not os.path.exists(PROMPT_FILE):
        print(f"[ERROR] Prompt file not found: {PROMPT_FILE}")
        sys.exit(1)
    system_prompt = load_system_prompt(PROMPT_FILE)
    print(f"[OK] System prompt loaded ({len(system_prompt)} chars)")

    # Azure OpenAI 클라이언트 한 번만 생성
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_ENDPOINT,
        api_key=required(API_KEY, "AZURE_OPENAI_API_KEY"),
        timeout=1200.0,  # 20분(1200초) 설정
    )
    print(f"[OK] Azure OpenAI client ready (deployment: {MODEL_DEPLOYMENT})")

    # 파일 목록
    if len(sys.argv) > 1:
        excel_files = [sys.argv[1]]
    else:
        excel_files = sorted([
            f for f in os.listdir(DATA_DIR)
            if (f.endswith(".xlsx") or f.endswith(".xlsm")) and not f.startswith("~$") and not f.startswith("abbreviation")
            # if (f.endswith(".xlsx") or f.endswith(".xlsm")) and not f.startswith("~$") and f != "R&N_MDL.xlsx"
        ])
        # 요청에 의해 R&N_MDL.xlsx 하나만 테스트하도록 하드코딩
        # excel_files = ["R&N_MDL.xlsx"]

    print(f"[OK] Target files: {excel_files}")

    for fname in excel_files:
        fpath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(fpath):
            print(f"[ERROR] File not found: {fpath}")
            continue
        base_name = os.path.splitext(fname)[0]
        output_path = os.path.join(OUTPUT_DIR, f"{base_name}_classified.csv")
        classify_file(client, system_prompt, fpath, output_path)

    print(f"\n{'=' * 60}")
    print(f"[DONE] Results in ./{OUTPUT_DIR}/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
