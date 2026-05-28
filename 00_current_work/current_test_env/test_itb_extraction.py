"""Extract ITB chunk metadata and retrieval queries with Azure OpenAI."""

from __future__ import annotations

import csv
import json
import os
import re
import time

from loguru import logger
from mdl_runtime.config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_CHAT_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    BASE_DIR,
    OUTPUT_DIR,
    REPO_ROOT,
    required,
)
from openai import AzureOpenAI

AZURE_ENDPOINT = AZURE_OPENAI_ENDPOINT
API_KEY = AZURE_OPENAI_API_KEY
API_VERSION = AZURE_OPENAI_CHAT_API_VERSION
MODEL_DEPLOYMENT = AZURE_OPENAI_CHAT_DEPLOYMENT

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(SCRIPT_DIR, "prompts", "itb_keyword_extraction_v2.md")
ABBREVIATION_RULES_PATH = REPO_ROOT / "src" / "common" / "normalization_rules" / "abbreviations.json"
ITB_SECTION = os.getenv("ITB_SECTION", "7").strip()
SECTION_CONFIG = {
    "6": {"min_page": 79, "max_page": 97},
    "7": {"min_page": 97, "max_page": 124},
}
if ITB_SECTION not in SECTION_CONFIG:
    raise ValueError("ITB_SECTION must be 6 or 7")

OUTPUT_STEM = f"output_itb_section{ITB_SECTION}_focused"
OUTPUT_FILE = str(OUTPUT_DIR / f"{OUTPUT_STEM}.csv")
JSON_OUTPUT_FILE = str(OUTPUT_DIR / f"{OUTPUT_STEM}.json")
TOKEN_OUTPUT_FILE = str(OUTPUT_DIR / "output_itb_tokens.csv")
CHUNKS_DIR = BASE_DIR / "data" / "itb_chunks"

OUTPUT_HEADER = [
    "Document",
    "Chunk ID",
    "Page",
    "Section",
    "Section Path",
    "Chunk Type",
    "Label",
    "Hierarchy Context",
    "1st Depth",
    "2nd Depth",
    "3rd Depth",
    "4th Depth",
    "5th Depth",
    "Keywords",
    "Search Query",
    "Search Query Source",
    "Confidence",
    "Needs Review",
    "Reason",
    "Chunk Text",
]
TOKEN_HEADER = ["Document", "Page", "Prompt Tokens", "Completion Tokens", "Total Tokens", "Chunk Text"]

TARGETS = [
    {
        "file": "R&N_ITB_chunks.json",
        "doc_name": "R&N_ITB",
        "min_page": SECTION_CONFIG[ITB_SECTION]["min_page"],
        "max_page": SECTION_CONFIG[ITB_SECTION]["max_page"],
    }
]

MAX_TEST_CHUNKS = int(os.getenv("MAX_TEST_CHUNKS", "0"))


def load_abbreviation_rules() -> dict[str, str]:
    """Load abbreviation variants mapped to canonical names."""
    payload = json.loads(ABBREVIATION_RULES_PATH.read_text(encoding="utf-8"))
    rules = {}
    for canonical, variants in payload.items():
        rules[canonical] = canonical
        for variant in variants:
            rules[variant] = canonical
    return rules


def find_known_abbreviations(text: str, rules: dict[str, str]) -> dict[str, str]:
    """Return abbreviation rules relevant to a chunk."""
    found = {}
    for variant, canonical in sorted(rules.items(), key=lambda item: len(item[0]), reverse=True):
        if variant.casefold() == canonical.casefold():
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(variant)}(?![A-Za-z0-9])", re.IGNORECASE)
        if pattern.search(text):
            found[variant] = canonical
    return found


def normalize_hierarchy(hierarchy: str, doc_name: str) -> str:
    """Remove local wrapper path parts from a chunk hierarchy."""
    parts = [part.strip() for part in hierarchy.split(" > ") if part.strip()]
    filtered_parts = [part for part in parts if part not in ("test_temp", doc_name)]
    return " > ".join(filtered_parts).replace(",", " ")


def parse_json_output(output: str) -> dict:
    """Parse a JSON object from a model response."""
    try:
        value = json.loads(output)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = output.find("{")
        end = output.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            value = json.loads(output[start : end + 1])
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def as_text(value) -> str:
    """Convert scalar values to clean text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def as_list_text(value) -> str:
    """Convert list-like values to comma-separated text."""
    if isinstance(value, list):
        return ", ".join(as_text(item) for item in value if as_text(item))
    return as_text(value)


def fallback_search_query(depths: list[str], keywords: str) -> str:
    """Build a query when the model omits one."""
    meaningful_depths = []
    generic_terms = {
        "note",
        "notes",
        "detail",
        "details",
        "general",
        "others",
        "other",
        "miscellaneous",
        "misc",
        "requirement",
        "requirements",
        "data",
        "information",
    }
    for depth in depths:
        if not depth or depth.strip().lower() in ("nan", "none"):
            continue
        cleaned_depth = re.sub(r"^[\d\._]+\s*", "", depth.strip()).strip()
        normalized_depth = re.sub(r"[^a-z0-9]+", " ", cleaned_depth.lower()).strip()
        if normalized_depth and normalized_depth not in generic_terms and not normalized_depth.isdigit():
            meaningful_depths.append(cleaned_depth)

    fallback_terms = []
    context = " ".join(meaningful_depths[-2:]) if meaningful_depths else ""
    cleaned_keywords = " ".join(
        keyword.strip()
        for keyword in keywords.split(",")
        if keyword.strip() and keyword.strip().lower() not in ("nan", "none")
    )
    if context:
        fallback_terms.append(context)
    if cleaned_keywords:
        fallback_terms.append(cleaned_keywords)
    return " ".join(fallback_terms).strip()


def build_csv_row(doc_name: str, chunk: dict, hierarchy: str, parsed: dict, text: str) -> list[str]:
    """Convert one structured model output to the CSV row schema."""
    pages = chunk.get("page_num", [])
    page_str = ", ".join(map(str, pages))
    depth1 = as_text(parsed.get("depth_1"))
    depth2 = as_text(parsed.get("depth_2"))
    depth3 = as_text(parsed.get("depth_3"))
    depth4 = as_text(parsed.get("depth_4"))
    depth5 = as_text(parsed.get("depth_5"))
    keywords = as_list_text(parsed.get("keywords"))
    search_query = as_text(parsed.get("search_query"))
    search_query_source = "llm" if search_query else "fallback"
    if not search_query:
        search_query = fallback_search_query([depth1, depth2, depth3, depth4, depth5], keywords)

    return [
        doc_name,
        as_text(chunk.get("chunk_id")),
        page_str,
        as_text(chunk.get("section")),
        as_list_text(chunk.get("section_path")),
        as_text(chunk.get("chunk_type")),
        as_list_text(chunk.get("label")),
        hierarchy,
        depth1,
        depth2,
        depth3,
        depth4,
        depth5,
        keywords,
        search_query,
        search_query_source,
        as_text(parsed.get("confidence")),
        as_text(parsed.get("needs_review")),
        as_text(parsed.get("reason")),
        text,
    ]


def build_json_record(
    doc_name: str,
    chunk: dict,
    hierarchy: str,
    parsed: dict,
    token_usage: dict,
    known_abbreviations: dict[str, str] | None = None,
    error: str = "",
) -> dict:
    """Build the JSONL source-of-truth record for one chunk."""
    record = {
        "document": doc_name,
        "chunk_id": chunk.get("chunk_id", ""),
        "pages": chunk.get("page_num", []),
        "section": chunk.get("section", ""),
        "section_path": chunk.get("section_path", ""),
        "chunk_type": chunk.get("chunk_type", ""),
        "label": chunk.get("label", ""),
        "chunk_size_tokens": chunk.get("chunk_size_tokens", ""),
        "extraction_confidence": chunk.get("extraction_confidence", ""),
        "hierarchy_context": hierarchy,
        "known_abbreviations": known_abbreviations or {},
        "llm_output": parsed,
        "token_usage": token_usage,
    }
    if error:
        record["error"] = error
    return record


def extract_chunk(client: AzureOpenAI, system_prompt: str, user_msg: str) -> tuple[dict, dict, str]:
    """Extract one chunk with the chat model."""
    response = client.chat.completions.create(
        model=MODEL_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.0,
        max_completion_tokens=2048,
        response_format={"type": "json_object"},
    )
    output = response.choices[0].message.content or "{}"
    token_usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        "total_tokens": response.usage.total_tokens if response.usage else 0,
    }
    return parse_json_output(output), token_usage, ""


def failed_extraction(exc: Exception) -> tuple[dict, dict, str]:
    """Build a failed extraction payload."""
    error = str(exc)
    return (
        {
            "depth_1": "ERROR",
            "depth_2": error,
            "keywords": [],
            "search_query": "",
            "confidence": "low",
            "needs_review": True,
            "reason": error,
        },
        {},
        error,
    )


def main() -> None:
    """Run ITB chunk extraction and write structured outputs."""
    logger.info("ITB Keyword Extraction Test -> Structured JSON + CSV Export")
    for target in TARGETS:
        logger.info("Target: {} (Pages {}~{})", target["doc_name"], target["min_page"], target["max_page"])

    if not os.path.exists(PROMPT_FILE):
        logger.error("Prompt file not found: {}", PROMPT_FILE)
        return
    with open(PROMPT_FILE, encoding="utf-8") as prompt_file:
        system_prompt = prompt_file.read()
    logger.info("System prompt loaded from {}", PROMPT_FILE)
    abbreviation_rules = load_abbreviation_rules()
    logger.info("Loaded {} abbreviation rules from {}", len(abbreviation_rules), ABBREVIATION_RULES_PATH)

    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_ENDPOINT,
        api_key=required(API_KEY, "AZURE_OPENAI_API_KEY"),
    )
    logger.info("Azure OpenAI client ready (deployment: {})", MODEL_DEPLOYMENT)

    with (
        open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as csv_file,
        open(TOKEN_OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as token_file,
    ):
        writer = csv.writer(csv_file)
        token_writer = csv.writer(token_file)
        writer.writerow(OUTPUT_HEADER)
        token_writer.writerow(TOKEN_HEADER)
        json_records = []

        for target in TARGETS:
            chunks_file = CHUNKS_DIR / target["file"]
            doc_name = target["doc_name"]

            if not chunks_file.exists():
                logger.error("Chunks file not found: {}", chunks_file)
                continue

            with open(chunks_file, encoding="utf-8") as input_file:
                data = json.load(input_file)
            chunks = data.get("chunks", [])

            target_chunks = []
            for chunk in chunks:
                pages = chunk.get("page_num", [])
                if any(target["min_page"] <= page <= target["max_page"] for page in pages):
                    target_chunks.append(chunk)
            if MAX_TEST_CHUNKS > 0:
                target_chunks = target_chunks[:MAX_TEST_CHUNKS]

            logger.info(
                "{}: found {} chunks for pages {}~{}",
                doc_name,
                len(target_chunks),
                target["min_page"],
                target["max_page"],
            )

            for index, chunk in enumerate(target_chunks, 1):
                text = chunk.get("text", "")
                hierarchy = normalize_hierarchy(chunk.get("hierarchy_context", ""), doc_name)
                known_abbreviations = find_known_abbreviations(f"{hierarchy}\n{text}", abbreviation_rules)
                pages = chunk.get("page_num", [])
                page_str = ", ".join(map(str, pages))

                if not text.strip():
                    continue

                logger.info(
                    "Processing {} chunk {}/{} (Pages: {})",
                    doc_name,
                    index,
                    len(target_chunks),
                    pages,
                )

                user_msg = json.dumps(
                    {
                        "document": doc_name,
                        "chunk_id": chunk.get("chunk_id", ""),
                        "pages": pages,
                        "section": chunk.get("section", ""),
                        "section_path": chunk.get("section_path", ""),
                        "chunk_type": chunk.get("chunk_type", ""),
                        "label": chunk.get("label", ""),
                        "hierarchy_context": hierarchy,
                        "known_abbreviations": known_abbreviations,
                        "chunk_text": text,
                    },
                    ensure_ascii=False,
                )

                error = ""
                try:
                    parsed, token_usage, error = extract_chunk(client, system_prompt, user_msg)
                except Exception as exc:
                    parsed, token_usage, error = failed_extraction(exc)
                    logger.exception("Chunk processing failed")

                writer.writerow(build_csv_row(doc_name, chunk, hierarchy, parsed, text))
                json_records.append(
                    build_json_record(
                        doc_name,
                        chunk,
                        hierarchy,
                        parsed,
                        token_usage,
                        known_abbreviations=known_abbreviations,
                        error=error,
                    )
                )
                token_writer.writerow(
                    [
                        doc_name,
                        page_str,
                        token_usage.get("prompt_tokens", 0),
                        token_usage.get("completion_tokens", 0),
                        token_usage.get("total_tokens", 0),
                        text,
                    ]
                )

                csv_file.flush()
                token_file.flush()
                if not error:
                    logger.info("Chunk processed OK (Tokens: {})", token_usage["total_tokens"])

                time.sleep(1.5)

    with open(JSON_OUTPUT_FILE, "w", encoding="utf-8") as json_file:
        json.dump(json_records, json_file, ensure_ascii=False, indent=2)
        json_file.write("\n")

    logger.info("Extraction tests completed. Results saved to {}", OUTPUT_FILE)
    logger.info("Structured JSON saved to {}", JSON_OUTPUT_FILE)


if __name__ == "__main__":
    main()
