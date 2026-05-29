"""
ITB → MDL matching via two parallel approaches:
  A) LLM extracts key terms from the depth hierarchy → Neo4j keyword filter (no vectors)
  B) Existing vector similarity search

Output CSV has both result columns side-by-side for comparison.

Usage:
  python match_itb_keyword_compare.py              # default: section 7
  ITB_SECTION=6 python match_itb_keyword_compare.py
"""

import json
import os
import re
import sys

import pandas as pd
from openai import AzureOpenAI
from tqdm import tqdm

from mdl_runtime.config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_CHAT_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    OUTPUT_DIR,
    required,
)
from mdl_runtime.embeddings import UnifiedEmbeddingService
from mdl_runtime.neo4j_connection import Neo4jConnection

# ── constants ───────────────────────────────────────────────────────────────
ITB_SECTION = os.getenv("ITB_SECTION", "7").strip()
TOP_K = 20          # documents returned per ITB row for each method
VECTOR_CANDIDATES = 50   # initial candidate pool from ANN before re-ranking
SCOPE_BONUS = 0.15

GENERIC_LABELS = {
    "note", "notes", "detail", "details", "general", "others", "other",
    "miscellaneous", "misc", "requirement", "requirements", "data", "information",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ITB_CSV = str(OUTPUT_DIR / f"output_itb_section{ITB_SECTION}_focused.csv")
OUTPUT_CSV = str(OUTPUT_DIR / f"output_match_keyword_compare_section{ITB_SECTION}.csv")


# ── depth helpers ────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    if not isinstance(text, str) or text.strip().lower() in ("nan", ""):
        return ""
    cleaned = re.sub(r'^[\d\.]+\s*', '', text)
    return cleaned.replace('_', ' ').strip()


def _is_meaningful(text: str) -> bool:
    cleaned = _clean(text)
    if not cleaned:
        return False
    norm = re.sub(r'[^a-z0-9]+', ' ', cleaned.lower()).strip()
    return bool(norm) and norm not in GENERIC_LABELS and not norm.isdigit()


def get_all_depths(row: dict) -> list[str]:
    """Return all non-empty, meaningful depth strings (1st–5th)."""
    result = []
    for col in ["1st Depth", "2nd Depth", "3rd Depth", "4th Depth", "5th Depth"]:
        v = str(row.get(col, ""))
        if _is_meaningful(v):
            result.append(_clean(v))
    return result


def get_depth_failure_type(row: dict) -> str | None:
    """
    Returns the failure reason for a row, or None if the row is fine.
      'EMPTY'       — 1st Depth is blank or nan (extraction never ran / returned nothing)
      'API_ERROR'   — 1st Depth starts with 'ERROR,' (LLM API call failed, e.g. timeout)
      'ALL_GENERIC' — Depths are filled but every value is a generic label like "General"
    """
    d1 = str(row.get("1st Depth", "")).strip()
    if not d1 or d1.lower() == "nan":
        return "EMPTY"
    if d1.upper().startswith("ERROR"):
        return "API_ERROR"
    if len(get_all_depths(row)) == 0:
        return "ALL_GENERIC"
    return None


def is_depth_missing(row: dict) -> bool:
    return get_depth_failure_type(row) is not None


# ── Goal 1: missing-depth report ─────────────────────────────────────────────

_FAILURE_LABELS = {
    "EMPTY":       "Blank 1st Depth — extraction never ran or returned nothing",
    "API_ERROR":   "API call failed — transient error, safe to retry",
    "ALL_GENERIC": "All depths are generic labels — needs manual review or re-extraction",
}

def report_missing_depths(df: pd.DataFrame) -> pd.DataFrame:
    tmp = df.copy()
    tmp["_failure_type"] = tmp.apply(get_depth_failure_type, axis=1)
    missing = tmp[tmp["_failure_type"].notna()].copy()

    print(f"\n[Depth Check] Total rows: {len(df)}")
    print(f"[Depth Check] Rows with depth issues: {len(missing)}")

    for ftype, label in _FAILURE_LABELS.items():
        group = missing[missing["_failure_type"] == ftype]
        if group.empty:
            continue
        print(f"\n  [{ftype}] {label} — {len(group)} row(s):")
        for _, row in group.iterrows():
            print(f"    Page {row.get('Page','?')}: "
                  f"1st='{row.get('1st Depth','')}' | "
                  f"Chunk: {str(row.get('Chunk Text',''))[:60]}…")

    # Return without the internal helper column
    return missing.drop(columns=["_failure_type"])


# ── Goal 2: LLM keyword extraction from depth ────────────────────────────────

_SYSTEM_PROMPT = """\
You are a technical document specialist for power-plant engineering projects.
Your job: extract 3–7 concise technical keyword phrases from an ITB section hierarchy.
These keywords will be used to search an MDL (Master Document List) by exact or partial text match.
Focus on:
  - Specific equipment names (e.g. "lube oil pump", "gas turbine generator")
  - System names (e.g. "closed cooling water system", "fuel gas supply")
  - Discipline / work type (e.g. "civil structural", "electrical protection")
Avoid generic terms like "general", "requirement", "data".
Return ONLY a JSON array of strings. No explanation."""


def extract_keywords_from_depth(
    depths: list[str],
    existing_keywords: str,
    client: AzureOpenAI,
    model: str,
) -> list[str]:
    """Ask LLM to distil the depth hierarchy into matchable keywords."""
    if not depths:
        # Fall back to splitting existing keywords column
        if existing_keywords and existing_keywords.lower() != "nan":
            return [k.strip() for k in existing_keywords.split(',') if k.strip()][:7]
        return []

    depth_text = "\n".join(f"  - Depth {i+1}: {d}" for i, d in enumerate(depths))
    user_msg = (
        f"ITB section hierarchy:\n{depth_text}\n\n"
        f"Existing keywords (for reference only): {existing_keywords}\n\n"
        "Extract 3–7 precise technical keyword phrases for MDL search."
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.0,
            max_completion_tokens=256,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code fences if present
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(k).strip() for k in parsed if str(k).strip()]
    except Exception as e:
        print(f"  [LLM warn] keyword extraction failed: {e}")

    # Fallback: tokenise existing keywords
    return [k.strip() for k in existing_keywords.split(',') if k.strip()][:5]


# ── Goal 3: Neo4j keyword filter (no vectors) ────────────────────────────────

_KW_QUERY = """
MATCH (n:TestMDLDocument)
WHERE size($keywords) > 0 AND ANY(kw IN $keywords WHERE
    toLower(n.title)       CONTAINS toLower(kw) OR
    toLower(n.equipment)   CONTAINS toLower(kw) OR
    toLower(n.system)      CONTAINS toLower(kw) OR
    toLower(n.building)    CONTAINS toLower(kw) OR
    toLower(n.study_survey) CONTAINS toLower(kw)
)
RETURN
    n.source_file   AS source_file,
    n.title         AS title,
    n.equipment     AS equipment,
    n.system        AS system,
    n.building      AS building,
    n.study_survey  AS study_survey,
    [kw IN $keywords WHERE
        toLower(n.title)       CONTAINS toLower(kw) OR
        toLower(n.equipment)   CONTAINS toLower(kw) OR
        toLower(n.system)      CONTAINS toLower(kw) OR
        toLower(n.building)    CONTAINS toLower(kw) OR
        toLower(n.study_survey) CONTAINS toLower(kw)
    ] AS matched_keywords
ORDER BY size(matched_keywords) DESC
LIMIT $top_k
"""


def keyword_filter_mdl(
    keywords: list[str],
    conn: Neo4jConnection,
    top_k: int = TOP_K,
    exclude_source: str | None = None,
) -> list[dict]:
    if not keywords:
        return []
    with conn.session() as session:
        result = session.run(
            _KW_QUERY,
            keywords=keywords,
            top_k=top_k,
        )
        rows = []
        for rec in result:
            sf = rec["source_file"] or ""
            if exclude_source and exclude_source.lower() in sf.lower():
                continue
            rows.append({
                "source_file": sf,
                "title": rec["title"] or "",
                "equipment": rec["equipment"] or "",
                "system": rec["system"] or "",
                "building": rec["building"] or "",
                "study_survey": rec["study_survey"] or "",
                "matched_keywords": list(rec["matched_keywords"]),
                "match_count": len(list(rec["matched_keywords"])),
            })
        rows.sort(key=lambda x: x["match_count"], reverse=True)
        return rows[:top_k]


# ── Goal 4: vector similarity search (existing logic, unchanged) ─────────────

_VEC_QUERY = """
CALL db.index.vector.queryNodes("test_mdl_document_vector_idx", $candidates, $embedding)
YIELD node, score
WHERE NOT (node.source_file CONTAINS "R&N_MDL")
RETURN
    node.source_file  AS source_file,
    node.title        AS title,
    node.system       AS system,
    node.equipment    AS equipment,
    node.building     AS building,
    node.study_survey AS study_survey,
    score
"""


def _scope_bonus(candidate: dict, query_text: str) -> float:
    bonus = 0.0
    qt = query_text.lower()
    for field in ("equipment", "system", "building", "study_survey"):
        val = str(candidate.get(field) or "").lower()
        if len(val) <= 2:
            continue
        parts = re.split(r'[/,;()]+', val)
        if val in qt or any(p.strip() and p.strip() in qt for p in parts):
            bonus += SCOPE_BONUS
    return bonus


def vector_search_mdl(
    search_query: str,
    emb_dict: dict,
    conn: Neo4jConnection,
    top_k: int = TOP_K,
    candidates: int = VECTOR_CANDIDATES,
) -> list[dict]:
    emb = emb_dict.get(search_query)
    if emb is None:
        return []
    with conn.session() as session:
        result = session.run(_VEC_QUERY, embedding=emb, candidates=candidates)
        rows = [dict(r) for r in result]

    ranked = []
    for r in rows:
        base = r["score"]
        bonus = _scope_bonus(r, search_query)
        ranked.append({**r, "base_score": base, "final_score": base + bonus})
    ranked.sort(key=lambda x: x["final_score"], reverse=True)
    # de-dup by title
    seen, out = set(), []
    for r in ranked:
        key = f"{r['source_file']}_{r['title']}"
        if key not in seen:
            seen.add(key)
            out.append(r)
        if len(out) >= top_k:
            break
    return out


# ── formatting helpers ───────────────────────────────────────────────────────

def _fmt_kw_doc(doc: dict, rank: int) -> str:
    proj = (doc["source_file"]
            .replace("_MDL.xlsx", "").replace("_classified.csv", "").replace(".xlsx", ""))
    kws = ", ".join(doc["matched_keywords"][:3]) if doc["matched_keywords"] else "-"
    return f"[{proj}] {doc['title']} (matched: {kws})"


def _fmt_vec_doc(doc: dict, rank: int) -> str:
    proj = (doc["source_file"]
            .replace("_MDL.xlsx", "").replace("_classified.csv", "").replace(".xlsx", ""))
    return f"[{proj}] {doc['title']} (vec: {doc['final_score']:.4f} / base: {doc['base_score']:.4f})"


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"=== ITB→MDL Keyword+Vector Comparison  (Section {ITB_SECTION}) ===")

    # Load ITB extraction CSV
    if not os.path.exists(ITB_CSV):
        print(f"[ERROR] ITB CSV not found: {ITB_CSV}")
        sys.exit(1)
    df = pd.read_csv(ITB_CSV, encoding="utf-8-sig")
    print(f"Loaded {len(df)} rows from {ITB_CSV}")

    # ── Goal 1: missing depth report ─────────────────────────────────────────
    missing_df = report_missing_depths(df)
    # Exclude error rows from matching
    process_df = df[~df.apply(is_depth_missing, axis=1)].copy()
    print(f"Rows available for matching: {len(process_df)}")

    # Init services
    print("\nInitialising Neo4j + Embedding service…")
    conn = Neo4jConnection()
    conn.connect()
    emb_svc = UnifiedEmbeddingService.build_default()
    llm_client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=required(AZURE_OPENAI_API_KEY, "AZURE_OPENAI_API_KEY"),
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
    )

    # ── Goal 2: extract depth keywords for every row via LLM ─────────────────
    print(f"\n[Step 2] Extracting depth keywords via LLM for {len(process_df)} rows…")
    depth_keywords_list: list[list[str]] = []
    for _, row in tqdm(process_df.iterrows(), total=len(process_df), desc="LLM keyword extraction"):
        depths = get_all_depths(row)
        existing_kw = str(row.get("Keywords", ""))
        kws = extract_keywords_from_depth(depths, existing_kw, llm_client, AZURE_OPENAI_CHAT_DEPLOYMENT)
        depth_keywords_list.append(kws)

    process_df = process_df.copy()
    process_df["Depth_Keywords"] = [", ".join(k) for k in depth_keywords_list]

    # ── Pre-compute vector embeddings (use Search Query column when available) ─
    search_queries: list[str] = []
    for _, row in process_df.iterrows():
        sq = str(row.get("Search Query", "")).strip()
        if sq and sq.lower() != "nan":
            search_queries.append(sq)
        else:
            depths = get_all_depths(row)
            search_queries.append(" ".join(depths[-2:]))

    unique_queries = list(set(search_queries))
    print(f"\n[Vector] Embedding {len(unique_queries)} unique search queries…")
    embeddings = emb_svc.embed_batch(unique_queries)
    emb_dict = dict(zip(unique_queries, embeddings))

    # ── Goals 3 & 4: keyword filter  +  vector search, side-by-side ──────────
    print("\n[Step 3+4] Running keyword filter and vector search…")
    output_rows = []

    for idx, (df_idx, row) in enumerate(tqdm(process_df.iterrows(), total=len(process_df), desc="Matching")):
        kws = depth_keywords_list[idx]
        sq  = search_queries[idx]

        # Goal 3 – keyword filter
        kw_docs = keyword_filter_mdl(kws, conn, top_k=TOP_K)

        # Goal 4 – vector similarity
        vec_docs = vector_search_mdl(sq, emb_dict, conn, top_k=TOP_K)

        out = row.to_dict()
        out["Depth_Keywords"] = ", ".join(kws)
        out["Search_Query_Used"] = sq

        for i in range(TOP_K):
            col_kw  = f"KW_Doc_{i+1}"
            col_vec = f"Vec_Doc_{i+1}"
            out[col_kw]  = _fmt_kw_doc(kw_docs[i],  i+1) if i < len(kw_docs)  else ""
            out[col_vec] = _fmt_vec_doc(vec_docs[i], i+1) if i < len(vec_docs) else ""

        output_rows.append(out)

    # Append missing-depth rows (flagged by type, no match results)
    skip_counts: dict[str, int] = {}
    for _, row in missing_df.iterrows():
        out = row.to_dict()
        ftype = get_depth_failure_type(out) or "UNKNOWN"
        skip_counts[ftype] = skip_counts.get(ftype, 0) + 1
        out["Depth_Keywords"] = f"[SKIPPED — {ftype}]"
        out["Search_Query_Used"] = ""
        for i in range(TOP_K):
            out[f"KW_Doc_{i+1}"]  = ""
            out[f"Vec_Doc_{i+1}"] = ""
        output_rows.append(out)

    result_df = pd.DataFrame(output_rows)
    result_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[Done] Results saved → {OUTPUT_CSV}")
    print(f"  Rows processed : {len(process_df)}")
    if skip_counts:
        for ftype, count in skip_counts.items():
            print(f"  Rows skipped [{ftype}]: {count}")
    else:
        print("  Rows skipped   : 0")


if __name__ == "__main__":
    main()
