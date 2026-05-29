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
VECTOR_INDEX_NAME = "test_mdl_document_vector_idx"
RETRIEVAL_MODE = os.getenv("ITB_RETRIEVAL_MODE", "keyword").strip().lower()
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
    return " ".join(depth_filter_terms).strip()


def split_phrase_terms(text):
    if not text or text.lower() == "nan":
        return []
    return [
        term.strip()
        for term in re.split(r"[,;\n]+", text)
        if term.strip()
    ]


def build_vector_terms(row, depth_filter_terms):
    return unique_preserve_order(depth_filter_terms)


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


def get_candidate_key(candidate):
    doc_id = candidate.get("doc_id")
    if doc_id:
        return f"doc_id:{doc_id}"
    return "|".join(
        str(candidate.get(field, ""))
        for field in ("source_file", "document_no", "title")
    )


def max_cosine_similarity(query_embeddings, candidate_embedding):
    scores = [
        score for score in (
            cosine_similarity(query_embedding, candidate_embedding)
            for query_embedding in query_embeddings
        )
        if score is not None
    ]
    if not scores:
        return None
    return max(scores)


def rerank_candidates_by_vector(candidates, query_embeddings):
    reranked_candidates = []
    for retrieval_rank, candidate in enumerate(candidates, start=1):
        reranked_candidate = dict(candidate)
        reranked_candidate.setdefault("retrieval_rank", retrieval_rank)
        reranked_candidate["vector_score"] = max_cosine_similarity(
            query_embeddings,
            reranked_candidate.pop("embedding", None),
        )
        reranked_candidates.append(reranked_candidate)

    return sorted(
        reranked_candidates,
        key=lambda candidate: (
            candidate["vector_score"] is not None,
            candidate["vector_score"] or -1.0,
            -candidate["retrieval_rank"],
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
           score AS bm25_score
    ORDER BY score DESC
    LIMIT $limit
    """

    with conn.session() as session:
        candidates = [
            dict(record)
            for record in session.run(
                query,
                index_name=FULLTEXT_INDEX_NAME,
                search_query=depth_filter_query,
                limit=limit,
            )
        ]
    for rank, candidate in enumerate(candidates, start=1):
        candidate["bm25_rank"] = rank
        candidate["retrieval_rank"] = rank
    return candidates


def semantic_search_mdl(conn, query_embedding, query_term, limit=BM25_CANDIDATE_LIMIT):
    if not query_embedding:
        return []

    query = f"""
    CALL db.index.vector.queryNodes("{VECTOR_INDEX_NAME}", $limit, $embedding)
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
           score AS semantic_score
    ORDER BY score DESC
    LIMIT $limit
    """

    with conn.session() as session:
        candidates = [
            dict(record)
            for record in session.run(
                query,
                embedding=query_embedding,
                limit=limit,
            )
        ]
    for rank, candidate in enumerate(candidates, start=1):
        candidate["semantic_rank"] = rank
        candidate["retrieval_rank"] = rank
        candidate["matched_terms"] = [query_term]
    return candidates


def merge_semantic_candidates(term_candidates):
    merged = {}

    for candidate in term_candidates:
        key = get_candidate_key(candidate)
        if key not in merged:
            merged[key] = dict(candidate)
            continue

        existing = merged[key]
        existing["matched_terms"] = unique_preserve_order(
            existing.get("matched_terms", []) + candidate.get("matched_terms", [])
        )
        if candidate.get("semantic_score", 0.0) > existing.get("semantic_score", 0.0):
            existing.update({
                "semantic_rank": candidate.get("semantic_rank"),
                "semantic_score": candidate.get("semantic_score"),
                "embedding": candidate.get("embedding") or existing.get("embedding"),
            })
        existing["retrieval_rank"] = min(
            existing.get("retrieval_rank") or BM25_CANDIDATE_LIMIT + 1,
            candidate.get("semantic_rank") or BM25_CANDIDATE_LIMIT + 1,
        )

    return sorted(
        merged.values(),
        key=lambda candidate: (
            -(len(candidate.get("matched_terms", []))),
            -(candidate.get("semantic_score") or 0.0),
            candidate.get("retrieval_rank") or BM25_CANDIDATE_LIMIT + 1,
        ),
    )


def semantic_search_mdl_by_terms(conn, query_term_embeddings):
    term_candidates = []
    for query_term, query_embedding in query_term_embeddings:
        term_candidates.extend(semantic_search_mdl(conn, query_embedding, query_term))
    return merge_semantic_candidates(term_candidates)


def merge_retrieval_candidates(keyword_candidates, semantic_candidates):
    merged = {}

    for candidate in keyword_candidates:
        key = get_candidate_key(candidate)
        merged[key] = dict(candidate)

    for candidate in semantic_candidates:
        key = get_candidate_key(candidate)
        if key in merged:
            merged[key].update({
                "semantic_rank": candidate.get("semantic_rank"),
                "semantic_score": candidate.get("semantic_score"),
                "embedding": candidate.get("embedding") or merged[key].get("embedding"),
                "matched_terms": candidate.get("matched_terms", []),
            })
            merged[key]["retrieval_rank"] = min(
                merged[key].get("bm25_rank") or BM25_CANDIDATE_LIMIT + 1,
                candidate.get("semantic_rank") or BM25_CANDIDATE_LIMIT + 1,
            )
        else:
            merged[key] = dict(candidate)

    return sorted(
        merged.values(),
        key=lambda candidate: candidate.get("retrieval_rank") or BM25_CANDIDATE_LIMIT + 1,
    )


def retrieve_candidates(conn, retrieval_mode, depth_filter_query, query_term_embeddings):
    keyword_candidates = []
    semantic_candidates = []

    if retrieval_mode in {"keyword", "hybrid"}:
        keyword_candidates = bm25_search_mdl(conn, depth_filter_query)

    if retrieval_mode in {"semantic", "hybrid"}:
        semantic_candidates = semantic_search_mdl_by_terms(conn, query_term_embeddings)

    if retrieval_mode == "keyword":
        candidates = keyword_candidates
    elif retrieval_mode == "semantic":
        candidates = semantic_candidates
    else:
        candidates = merge_retrieval_candidates(keyword_candidates, semantic_candidates)

    return candidates, keyword_candidates, semantic_candidates


def format_candidate(candidate):
    project = (
        str(candidate["source_file"])
        .replace("_MDL.xlsx", "")
        .replace("_classified.csv", "")
        .replace(".xlsx", "")
    )
    parts = []
    vector_score = candidate.get("vector_score")
    if vector_score is not None:
        parts.append(f"Vector: {vector_score:.4f}")
    if candidate.get("bm25_score") is not None:
        parts.append(f"BM25: {candidate['bm25_score']:.4f}")
    if candidate.get("semantic_score") is not None:
        parts.append(f"Semantic: {candidate['semantic_score']:.4f}")
    score_text = " / ".join(parts) if parts else "No score"
    return f"[{project}] {candidate['title']} ({score_text})"


def json_safe_value(value):
    if pd.isna(value):
        return ""
    return value


def format_json_candidate(candidate, rank):
    return {
        "rank": rank,
        "retrieval_rank": candidate.get("retrieval_rank"),
        "bm25_rank": candidate.get("bm25_rank"),
        "semantic_rank": candidate.get("semantic_rank"),
        "doc_id": json_safe_value(candidate.get("doc_id")),
        "source_file": json_safe_value(candidate.get("source_file")),
        "document_no": json_safe_value(candidate.get("document_no")),
        "title": json_safe_value(candidate.get("title")),
        "equipment": json_safe_value(candidate.get("equipment")),
        "building": json_safe_value(candidate.get("building")),
        "system": json_safe_value(candidate.get("system")),
        "study_survey": json_safe_value(candidate.get("study_survey")),
        "deliverable": json_safe_value(candidate.get("deliverable")),
        "bm25_score": candidate.get("bm25_score"),
        "semantic_score": candidate.get("semantic_score"),
        "vector_score": candidate.get("vector_score"),
        "matched_terms": candidate.get("matched_terms", []),
    }


def build_json_record(
    source_row,
    depth_filter_query,
    depth_filter_terms,
    vector_query,
    vector_terms,
    retrieval_mode,
    vector_rerank_enabled,
    retrieval_candidates,
    keyword_candidate_count,
    semantic_candidate_count,
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
        "vector_terms": vector_terms,
        "retrieval_mode": retrieval_mode,
        "vector_rerank_enabled": vector_rerank_enabled,
        "retrieval_candidate_count": len(retrieval_candidates),
        "keyword_candidate_count": keyword_candidate_count,
        "semantic_candidate_count": semantic_candidate_count,
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

    logger.info("Running Neo4j candidate retrieval (mode: {})...", RETRIEVAL_MODE)
    new_rows = []
    json_records = []

    vector_embeddings = {}
    if embedding_service is not None:
        vector_terms = []
        for _, source_row in target_df.iterrows():
            _, depth_filter_terms = build_depth_filter_query(source_row)
            vector_terms.extend(build_vector_terms(source_row, depth_filter_terms))

        unique_vector_terms = unique_preserve_order(vector_terms)
        logger.info("Embedding {} unique vector terms...", len(unique_vector_terms))
        embeddings = embedding_service.embed_batch(unique_vector_terms)
        vector_embeddings = dict(zip(unique_vector_terms, embeddings))

    for _, source_row in tqdm(target_df.iterrows(), total=len(target_df)):
        depth_filter_query, depth_filter_terms = build_depth_filter_query(source_row)
        vector_query = build_vector_query(source_row, depth_filter_terms)
        vector_terms = build_vector_terms(source_row, depth_filter_terms)
        query_term_embeddings = [
            (term, vector_embeddings[term])
            for term in vector_terms
            if term in vector_embeddings
        ]
        retrieval_candidates, keyword_candidates, semantic_candidates = retrieve_candidates(
            conn,
            RETRIEVAL_MODE,
            depth_filter_query,
            query_term_embeddings,
        )
        if ENABLE_VECTOR_RERANK and query_term_embeddings:
            reranked_candidates = rerank_candidates_by_vector(
                retrieval_candidates,
                [embedding for _, embedding in query_term_embeddings],
            )
        else:
            reranked_candidates = retrieval_candidates
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
        row["Vector_Terms"] = ", ".join(vector_terms)
        row["Retrieval_Mode"] = RETRIEVAL_MODE
        row["Vector_Rerank_Enabled"] = ENABLE_VECTOR_RERANK
        row["Retrieval_Candidate_Count"] = len(retrieval_candidates)
        row["Keyword_Candidate_Count"] = len(keyword_candidates)
        row["Semantic_Candidate_Count"] = len(semantic_candidates)
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
                vector_terms,
                RETRIEVAL_MODE,
                ENABLE_VECTOR_RERANK,
                retrieval_candidates,
                len(keyword_candidates),
                len(semantic_candidates),
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
        "Vector_Terms",
        "Retrieval_Mode",
        "Vector_Rerank_Enabled",
        "Retrieval_Candidate_Count",
        "Keyword_Candidate_Count",
        "Semantic_Candidate_Count",
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
    needs_embedding = ENABLE_VECTOR_RERANK or RETRIEVAL_MODE in {"semantic", "hybrid"}
    embedding_service = UnifiedEmbeddingService.build_default() if needs_embedding else None
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
