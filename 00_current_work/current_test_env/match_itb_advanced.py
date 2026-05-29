import json
import os
import re

import pandas as pd
from loguru import logger
from tqdm import tqdm

from mdl_runtime.config import OUTPUT_DIR
from mdl_runtime.embeddings import UnifiedEmbeddingService
from mdl_runtime.neo4j_connection import Neo4jConnection


DEPTH_COLUMNS = ("1st Depth", "2nd Depth", "3rd Depth", "4th Depth", "5th Depth")
FULLTEXT_INDEX_NAME = "test_mdl_document_fulltext_idx"
BM25_CANDIDATE_LIMIT = int(os.getenv("ITB_BM25_CANDIDATES", "100"))
BM25_OUTPUT_LIMIT = int(os.getenv("ITB_BM25_OUTPUT_LIMIT", "20"))
ENABLE_VECTOR_RERANK = os.getenv("ITB_ENABLE_VECTOR_RERANK", "true").lower() in {"1", "true", "yes", "y"}


def get_depth_context(row):
    depth_terms = get_depth_filter_terms(row)
    if not depth_terms:
        return ""
    return " ".join(depth_terms[-2:])


def unique_preserve_order(values):
    seen = set()
    unique_values = []
    for value in values:
        normalized = value.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(value)
    return unique_values


def get_depth_filter_terms(row):
    """Use only source-grounded depth phrases for BM25 filtering."""
    terms = []
    for depth in DEPTH_COLUMNS:
        value = str(row.get(depth, ""))
        value = value.strip()
        if not value or value.lower() == "nan":
            continue
        terms.append(value)
    return unique_preserve_order(terms)


def normalize_lucene_text(text):
    return re.sub(r"[^A-Za-z0-9]+", " ", text).strip()


def build_depth_filter_query(row):
    terms = get_depth_filter_terms(row)
    if not terms:
        return "", []

    clauses = []
    for term in terms:
        normalized_term = normalize_lucene_text(term)
        if not normalized_term:
            continue
        if " " in normalized_term:
            clauses.append(f'"{normalized_term}"')
        else:
            clauses.append(normalized_term)

    if not clauses:
        return "", terms

    return " OR ".join(clauses), terms


def build_vector_query(row, depth_filter_terms):
    search_query = str(row.get("Search Query", "")).strip()
    if search_query and search_query.lower() != "nan":
        return search_query

    keywords = str(row.get("Keywords", "")).strip()
    if keywords.lower() == "nan":
        keywords = ""

    parts = []
    if depth_filter_terms:
        parts.extend(depth_filter_terms[-2:])
    if keywords:
        parts.append(keywords)

    return " ".join(parts).strip()


def cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return None

    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right):
        dot += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value

    if left_norm == 0.0 or right_norm == 0.0:
        return None

    return dot / ((left_norm ** 0.5) * (right_norm ** 0.5))


def rerank_candidates_by_vector(bm25_candidates, query_embedding):
    reranked_candidates = []
    for bm25_rank, candidate in enumerate(bm25_candidates, start=1):
        reranked_candidate = dict(candidate)
        reranked_candidate["bm25_rank"] = bm25_rank
        reranked_candidate["vector_score"] = cosine_similarity(
            query_embedding,
            reranked_candidate.pop("embedding", None),
        )
        reranked_candidates.append(reranked_candidate)

    return sorted(
        reranked_candidates,
        key=lambda candidate: (
            candidate["vector_score"] is not None,
            candidate["vector_score"] or -1.0,
            -candidate["bm25_rank"],
        ),
        reverse=True,
    )


def setup_fulltext_index(conn):
    with conn.session() as session:
        session.run(f"""
        CREATE FULLTEXT INDEX {FULLTEXT_INDEX_NAME} IF NOT EXISTS
        FOR (n:TestMDLDocument)
        ON EACH [
            n.title,
            n.equipment,
            n.building,
            n.system,
            n.study_survey,
            n.deliverable,
            n.text_content
        ]
        """)


def bm25_search_mdl(conn, depth_filter_query, limit=BM25_CANDIDATE_LIMIT):
    if not depth_filter_query:
        return []

    query = """
    CALL db.index.fulltext.queryNodes($index_name, $search_query, {limit: $limit})
    YIELD node, score
    WHERE NOT coalesce(node.source_file, "") CONTAINS "R&N_MDL"
    RETURN node.doc_id AS doc_id,
           node.source_file AS source_file,
           node.document_no AS document_no,
           node.title AS title,
           node.system AS system,
           node.equipment AS equipment,
           node.building AS building,
           node.study_survey AS study_survey,
           node.deliverable AS deliverable,
           node.embedding AS embedding,
           score
    ORDER BY score DESC
    LIMIT $limit
    """

    with conn.session() as session:
        return [
            dict(record)
            for record in session.run(
                query,
                index_name=FULLTEXT_INDEX_NAME,
                search_query=depth_filter_query,
                limit=limit,
            )
        ]


def format_candidate(candidate):
    project = (
        str(candidate["source_file"])
        .replace("_MDL.xlsx", "")
        .replace("_classified.csv", "")
        .replace(".xlsx", "")
    )
    vector_score = candidate.get("vector_score")
    if vector_score is not None:
        return f"[{project}] {candidate['title']} (Vector: {vector_score:.4f} / BM25: {candidate['score']:.4f})"
    return f"[{project}] {candidate['title']} (BM25: {candidate['score']:.4f})"


def json_safe_value(value):
    if pd.isna(value):
        return ""
    return value


def format_json_candidate(candidate, rank):
    return {
        "rank": rank,
        "bm25_rank": int(candidate.get("bm25_rank", rank)),
        "doc_id": json_safe_value(candidate.get("doc_id")),
        "source_file": json_safe_value(candidate.get("source_file")),
        "document_no": json_safe_value(candidate.get("document_no")),
        "title": json_safe_value(candidate.get("title")),
        "equipment": json_safe_value(candidate.get("equipment")),
        "building": json_safe_value(candidate.get("building")),
        "system": json_safe_value(candidate.get("system")),
        "study_survey": json_safe_value(candidate.get("study_survey")),
        "deliverable": json_safe_value(candidate.get("deliverable")),
        "bm25_score": float(candidate.get("score", 0.0)),
        "vector_score": candidate.get("vector_score"),
    }


def build_json_record(
    source_row,
    depth_filter_query,
    depth_filter_terms,
    vector_query,
    vector_rerank_enabled,
    bm25_candidates,
    vector_candidate_count,
    top_matches,
):
    return {
        "document": json_safe_value(source_row.get("Document", "")),
        "chunk_id": json_safe_value(source_row.get("Chunk ID", "")),
        "page": json_safe_value(source_row.get("Page", "")),
        "depths": {
            depth: json_safe_value(source_row.get(depth, ""))
            for depth in DEPTH_COLUMNS
        },
        "depth_context": get_depth_context(source_row),
        "depth_filter_query": depth_filter_query,
        "depth_filter_terms": depth_filter_terms,
        "vector_query": vector_query,
        "vector_rerank_enabled": vector_rerank_enabled,
        "bm25_candidate_count": len(bm25_candidates),
        "vector_candidate_count": vector_candidate_count,
        "keywords": json_safe_value(source_row.get("Keywords", "")),
        "search_query": json_safe_value(source_row.get("Search Query", "")),
        "candidates": [
            format_json_candidate(candidate, rank)
            for rank, candidate in enumerate(top_matches, start=1)
        ],
    }


def json_output_path(csv_output_path):
    root, _ = os.path.splitext(str(csv_output_path))
    return f"{root}.json"


def process_file(csv_path, output_path, conn, embedding_service):
    logger.info("Reading input file: {}", csv_path)
    df = pd.read_csv(csv_path)

    target_df = df.copy()
    logger.info("Rows to process: {}", len(target_df))

    if len(target_df) == 0:
        logger.info("No target rows. Skipping.")
        return

    logger.info("Running Neo4j BM25 depth keyword filtering...")
    new_rows = []
    json_records = []

    vector_embeddings = {}
    if ENABLE_VECTOR_RERANK:
        vector_queries = []
        for _, source_row in target_df.iterrows():
            _, depth_filter_terms = build_depth_filter_query(source_row)
            vector_query = build_vector_query(source_row, depth_filter_terms)
            if vector_query:
                vector_queries.append(vector_query)

        unique_vector_queries = unique_preserve_order(vector_queries)
        logger.info("Embedding {} unique vector rerank queries...", len(unique_vector_queries))
        embeddings = embedding_service.embed_batch(unique_vector_queries)
        vector_embeddings = dict(zip(unique_vector_queries, embeddings))

    for _, source_row in tqdm(target_df.iterrows(), total=len(target_df)):
        depth_filter_query, depth_filter_terms = build_depth_filter_query(source_row)
        vector_query = build_vector_query(source_row, depth_filter_terms)
        bm25_candidates = bm25_search_mdl(conn, depth_filter_query)
        if ENABLE_VECTOR_RERANK and vector_query:
            reranked_candidates = rerank_candidates_by_vector(
                bm25_candidates,
                vector_embeddings.get(vector_query),
            )
        else:
            reranked_candidates = bm25_candidates
        vector_candidate_count = sum(
            1 for candidate in reranked_candidates
            if candidate.get("vector_score") is not None
        )
        top_matches = reranked_candidates[:BM25_OUTPUT_LIMIT]

        row = source_row.to_dict()
        row["Depth_Context"] = get_depth_context(source_row)
        row["Depth_Filter_Query"] = depth_filter_query
        row["Depth_Filter_Terms"] = ", ".join(depth_filter_terms)
        row["Vector_Query"] = vector_query
        row["Vector_Rerank_Enabled"] = ENABLE_VECTOR_RERANK
        row["BM25_Candidate_Count"] = len(bm25_candidates)
        row["Vector_Candidate_Count"] = vector_candidate_count
        row["Search_Queries"] = depth_filter_query

        for i in range(BM25_OUTPUT_LIMIT):
            col_name = f"Matched_Doc_{i + 1}"
            row[col_name] = format_candidate(top_matches[i]) if i < len(top_matches) else ""

        new_rows.append(row)
        json_records.append(
            build_json_record(
                source_row,
                depth_filter_query,
                depth_filter_terms,
                vector_query,
                ENABLE_VECTOR_RERANK,
                bm25_candidates,
                vector_candidate_count,
                top_matches,
            )
        )

    base_cols = [
        "Document",
        "Page",
        "1st Depth",
        "2nd Depth",
        "3rd Depth",
        "4th Depth",
        "5th Depth",
        "Depth_Context",
        "Depth_Filter_Query",
        "Depth_Filter_Terms",
        "Vector_Query",
        "Vector_Rerank_Enabled",
        "BM25_Candidate_Count",
        "Vector_Candidate_Count",
        "Keywords",
        "Search Query",
        "Search Query Source",
        "Search_Queries",
        "Chunk Text",
    ]
    match_cols = [f"Matched_Doc_{i + 1}" for i in range(BM25_OUTPUT_LIMIT)]

    result_df = pd.DataFrame(new_rows)
    final_cols = [c for c in base_cols if c in result_df.columns] + match_cols
    result_df = result_df[final_cols]

    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info("Saved successfully: {}", output_path)

    json_path = json_output_path(output_path)
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(json_records, file, ensure_ascii=False, indent=2)
    logger.info("Structured JSON saved successfully: {}", json_path)


def main():
    embedding_service = UnifiedEmbeddingService.build_default() if ENABLE_VECTOR_RERANK else None
    conn = Neo4jConnection()
    conn.connect()

    files_to_process = [
        {
            "in": str(OUTPUT_DIR / "output_itb_section6_focused.csv"),
            "out": str(OUTPUT_DIR / "output_match_all_projects_section6.csv"),
        },
        {
            "in": str(OUTPUT_DIR / "output_itb_section7_focused.csv"),
            "out": str(OUTPUT_DIR / "output_match_all_projects_section7.csv"),
        },
    ]

    try:
        setup_fulltext_index(conn)
        for file_pair in files_to_process:
            if os.path.exists(file_pair["in"]):
                process_file(file_pair["in"], file_pair["out"], conn, embedding_service)
            else:
                logger.warning("Input file not found: {}", file_pair["in"])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
