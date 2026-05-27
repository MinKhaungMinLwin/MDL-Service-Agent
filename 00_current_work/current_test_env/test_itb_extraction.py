import os
import json
import time
from openai import AzureOpenAI
import csv
import io

from mdl_runtime.config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_CHAT_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    BASE_DIR,
    OUTPUT_DIR,
    required,
)

# ── Azure OpenAI 설정 (기존 코드 참조) ─────────────────────────
AZURE_ENDPOINT = AZURE_OPENAI_ENDPOINT
API_KEY = AZURE_OPENAI_API_KEY
API_VERSION = AZURE_OPENAI_CHAT_API_VERSION
MODEL_DEPLOYMENT = AZURE_OPENAI_CHAT_DEPLOYMENT

script_dir = os.path.dirname(os.path.abspath(__file__))

# 프롬프트 파일 경로 (동일 폴더 내)
PROMPT_FILE = os.path.join(script_dir, "itb_keyword_extraction_prompt.md")
ITB_SECTION = os.getenv("ITB_SECTION", "7").strip()
SECTION_CONFIG = {
    "6": {"min_page": 79, "max_page": 97},
    "7": {"min_page": 97, "max_page": 124},
}
if ITB_SECTION not in SECTION_CONFIG:
    raise ValueError("ITB_SECTION must be 6 or 7")

# 결과를 저장할 출력 파일
OUTPUT_FILE = str(OUTPUT_DIR / f"output_itb_section{ITB_SECTION}_focused.csv")
# 토큰 사용량을 별도로 기록할 파일
TOKEN_OUTPUT_FILE = str(OUTPUT_DIR / "output_itb_tokens.csv")
CHUNKS_DIR = BASE_DIR / "data" / "itb_chunks"
OUTPUT_HEADER = [
    "Document", "Page", "1st Depth", "2nd Depth", "3rd Depth",
    "4th Depth", "5th Depth", "Keywords", "Search Query", "Search Query Source", "Chunk Text"
]
TOKEN_HEADER = ["Document", "Page", "Prompt Tokens", "Completion Tokens", "Total Tokens", "Chunk Text"]

# 작업 대상 문서 및 페이지 범위 설정
TARGETS = [
    {
        "file": "R&N_ITB_chunks.json",
        "doc_name": "R&N_ITB",
        "min_page": SECTION_CONFIG[ITB_SECTION]["min_page"],
        "max_page": SECTION_CONFIG[ITB_SECTION]["max_page"]
    }
]

MAX_TEST_CHUNKS = int(os.getenv("MAX_TEST_CHUNKS", "0"))

def header_matches(path, expected_header):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            return next(reader) == expected_header
        except StopIteration:
            return False

def main():
    print("=" * 60)
    print("ITB Keyword Extraction Test -> CSV Export (Append Mode)")
    print("Targets:")
    for t in TARGETS:
        print(f"  - {t['doc_name']} (Pages {t['min_page']}~{t['max_page']})")
    print("=" * 60)

    # 1. 프롬프트 로드
    if not os.path.exists(PROMPT_FILE):
        print(f"[ERROR] Prompt file not found: {PROMPT_FILE}")
        return
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        system_prompt = f.read()
    print(f"[OK] System prompt loaded from {PROMPT_FILE}")

    # 2. Azure OpenAI 클라이언트 초기화
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_ENDPOINT,
        api_key=required(API_KEY, "AZURE_OPENAI_API_KEY"),
    )
    print(f"[OK] Azure OpenAI client ready (deployment: {MODEL_DEPLOYMENT})\n")

    # 3. 문서 순회하며 청크 필터링 및 처리
    file_has_expected_header = header_matches(OUTPUT_FILE, OUTPUT_HEADER)
    token_file_has_expected_header = header_matches(TOKEN_OUTPUT_FILE, TOKEN_HEADER)
    output_mode = "a" if file_has_expected_header else "w"
    token_output_mode = "a" if token_file_has_expected_header else "w"
    if os.path.exists(OUTPUT_FILE) and not file_has_expected_header:
        print(f"[WARN] Existing output schema differs; rewriting with new header: {OUTPUT_FILE}")
    
    with open(OUTPUT_FILE, output_mode, encoding="utf-8-sig", newline="") as f_out, \
         open(TOKEN_OUTPUT_FILE, token_output_mode, encoding="utf-8-sig", newline="") as f_token:
        writer = csv.writer(f_out)
        token_writer = csv.writer(f_token)
        
        # 어떤 문서인지 구분하기 위해 Document 열을 맨 앞에 추가
        if output_mode == "w":
            writer.writerow(OUTPUT_HEADER)
            
        if token_output_mode == "w":
            token_writer.writerow(TOKEN_HEADER)

        for target in TARGETS:
            chunks_file = CHUNKS_DIR / target["file"]
            doc_name = target["doc_name"]
            
            if not chunks_file.exists():
                print(f"[ERROR] Chunks file not found: {chunks_file}")
                continue
                
            with open(chunks_file, "r", encoding="utf-8") as f_in:
                data = json.load(f_in)
            chunks = data.get("chunks", [])
            
            # 페이지 범위에 해당하는 청크 필터링
            target_chunks = []
            for c in chunks:
                pages = c.get("page_num", [])
                if any(target["min_page"] <= p <= target["max_page"] for p in pages):
                    target_chunks.append(c)
            if MAX_TEST_CHUNKS > 0:
                target_chunks = target_chunks[:MAX_TEST_CHUNKS]
                    
            print(f"[{doc_name}] Found {len(target_chunks)} chunks for pages {target['min_page']}~{target['max_page']}")
            
            for i, chunk in enumerate(target_chunks, 1):
                text = chunk.get("text", "")
                hierarchy = chunk.get("hierarchy_context", "")
                
                # 불필요한 경로(test_temp, 파일명) 제거
                parts = [p.strip() for p in hierarchy.split(" > ") if p.strip()]
                filtered_parts = [p for p in parts if p not in ("test_temp", doc_name)]
                hierarchy = " > ".join(filtered_parts).replace(",", " ")
                
                pages = chunk.get("page_num", [])
                page_str = ", ".join(map(str, pages))
                
                if not text.strip():
                    continue
                    
                print(f"  Processing {doc_name} chunk {i}/{len(target_chunks)} (Pages: {pages})...", end=" ", flush=True)
                
                user_msg = f'hierarchy_context = "{hierarchy}"\nchunk_text = "{text}"'
                
                try:
                    response = client.chat.completions.create(
                        model=MODEL_DEPLOYMENT,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_msg},
                        ],
                        temperature=0.0,
                        max_completion_tokens=2048,
                    )
                    output = response.choices[0].message.content
                    
                    # 토큰 사용량 추출
                    prompt_tokens = response.usage.prompt_tokens if response.usage else 0
                    comp_tokens = response.usage.completion_tokens if response.usage else 0
                    total_tokens = response.usage.total_tokens if response.usage else 0
                    
                    csv_line = ""
                    for line in output.splitlines():
                        clean_line = line.strip()
                        if clean_line and not clean_line.startswith("```"):
                            csv_line = clean_line
                            break
                    
                    if csv_line:
                        reader = csv.reader(io.StringIO(csv_line))
                        parsed_row = next(reader)
                        if len(parsed_row) <= 5:
                            parsed_row += [""] * (5 - len(parsed_row))
                            depth1, depth2, depth3, depth4, keywords = parsed_row[:5]
                            depth5, search_query = "", ""
                        else:
                            parsed_row += [""] * (7 - len(parsed_row))
                            depth1, depth2, depth3, depth4, depth5, keywords, search_query = parsed_row[:7]
                    else:
                        depth1, depth2, depth3, depth4, depth5, keywords, search_query = "", "", "", "", "", "", ""
                    
                    search_query_source = "llm" if search_query.strip() else "fallback"
                    # Ensure Search Query is never empty
                    if not search_query.strip():
                        import re
                        meaningful_depths = []
                        for d in [depth1, depth2, depth3, depth4, depth5]:
                            if d and d.strip() and d.strip().lower() not in ("nan", "none", ""):
                                # Clean numbering and underscores
                                cleaned_d = re.sub(r'^[\d\._]+\s*', '', d.strip()).strip()
                                normalized_d = re.sub(r'[^a-z0-9]+', ' ', cleaned_d.lower()).strip()
                                if (normalized_d and 
                                    normalized_d not in ("note", "notes", "detail", "details", "general", "others", "other", "miscellaneous", "misc", "requirement", "requirements", "data", "information") and 
                                    not normalized_d.isdigit()):
                                    meaningful_depths.append(cleaned_d)
                        
                        context = " ".join(meaningful_depths[-2:]) if meaningful_depths else ""
                        cleaned_kw = " ".join([k.strip() for k in keywords.split(',') if k.strip() and k.strip().lower() not in ("nan", "none")])
                        
                        fallback_terms = []
                        if context:
                            fallback_terms.append(context)
                        if cleaned_kw:
                            fallback_terms.append(cleaned_kw)
                        
                        search_query = " ".join(fallback_terms).strip()
                        
                    # 1. 기존 추출 결과 저장
                    writer.writerow([
                        doc_name, page_str, depth1, depth2, depth3, depth4, depth5,
                        keywords, search_query, search_query_source, text
                    ])
                    f_out.flush()
                    
                    # 2. 토큰 수 별도 파일에 저장
                    token_writer.writerow([doc_name, page_str, prompt_tokens, comp_tokens, total_tokens, text])
                    f_token.flush()
                    
                    print(f"OK (Tokens: {total_tokens})")
                except Exception as e:
                    writer.writerow([doc_name, page_str, "ERROR", str(e), "", "", "", "", "", "", text])
                    token_writer.writerow([doc_name, page_str, 0, 0, 0, text])
                    print("FAILED")
                    
                time.sleep(1.5)
            print("-" * 60)

    print(f"\n[DONE] Extraction tests completed. Results saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
