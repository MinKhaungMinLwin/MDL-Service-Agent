import os
import pandas as pd
from tqdm import tqdm
import re

from mdl_runtime.config import OUTPUT_DIR
from mdl_runtime.neo4j_connection import Neo4jConnection
from mdl_runtime.embeddings import UnifiedEmbeddingService

GENERIC_DEPTH_LABELS = {
    "note", "notes", "detail", "details", "general", "others", "other",
    "miscellaneous", "misc", "requirement", "requirements", "data", "information",
}
SCOPE_MATCH_BONUS = 0.15

def clean_depth_text(text):
    if not isinstance(text, str) or text == 'nan':
        return ""
    # "6.1.1 " 같은 숫자 번호 매기기 제거 및 밑줄(_)을 공백으로 변경
    cleaned = re.sub(r'^[\d\.]+\s*', '', text)
    cleaned = cleaned.replace('_', ' ')
    return cleaned.strip()

def is_meaningful_depth(text):
    cleaned = clean_depth_text(text)
    if not cleaned:
        return False
    normalized = re.sub(r'[^a-z0-9]+', ' ', cleaned.lower()).strip()
    return bool(normalized) and normalized not in GENERIC_DEPTH_LABELS and not normalized.isdigit()

def get_depth_context(row):
    """1~5 Depth 중 검색에 유의미한 Depth를 선택합니다."""
    meaningful_depths = []
    for depth in ['1st Depth', '2nd Depth', '3rd Depth', '4th Depth', '5th Depth']:
        val = str(row.get(depth, ''))
        if is_meaningful_depth(val):
            meaningful_depths.append(clean_depth_text(val))
    if not meaningful_depths:
        return ""
    return " ".join(meaningful_depths[-2:])

def get_search_queries(row, keywords):
    """LLM 생성 Search Query를 우선 사용하고, 없으면 Depth+Keyword 쿼리를 구성합니다."""
    llm_query = str(row.get('Search Query', ''))
    if llm_query != 'nan' and llm_query.strip():
        return [{'keyword': llm_query.strip(), 'search_query': llm_query.strip()}]

    context = get_depth_context(row)
    queries = []
    for kw in keywords:
        search_query = f"{context} {kw}".strip()
        if search_query:
            queries.append({'keyword': kw, 'search_query': search_query})
    return queries

def add_scope_bonus(candidate, search_query, keyword):
    """Equipment/System/Building/Study-Survey는 동일 가중치로 반영합니다."""
    query_text = f"{search_query} {keyword}".lower()
    bonus = 0.0
    for field in ('equipment', 'system', 'building', 'study_survey'):
        scope_val = str(candidate[field]).lower() if candidate[field] else ""
        if len(scope_val) <= 2:
            continue
        if scope_val in query_text or any(part and part in query_text for part in re.split(r'[/,;()]+', scope_val)):
            bonus += SCOPE_MATCH_BONUS
    return bonus

def process_file(csv_path, output_path, embedding_service, conn):
    print(f"\n입력 파일 읽는 중: {csv_path}")
    df = pd.read_csv(csv_path)
    
    target_df = df.copy()
    print(f"처리 대상 데이터 수: {len(target_df)} 개")
    
    if len(target_df) == 0:
        print("대상 데이터가 없어 건너뜁니다.")
        return
        
    # 각 섹션(행) 단위로 키워드를 그룹화하여 처리
    unique_queries = set()
    section_queries = []
    
    for _, row in target_df.iterrows():
        kw_str = str(row.get('Keywords', ''))
        if kw_str == 'nan' or not kw_str.strip():
            continue
            
        individual_keywords = [k.strip() for k in kw_str.split(',') if k.strip()]

        context = get_depth_context(row)
        queries_for_this_row = get_search_queries(row, individual_keywords)
        for q in queries_for_this_row:
            search_query = q['search_query']
            unique_queries.add(search_query)
            
        if queries_for_this_row:
            section_queries.append({
                'original_row': row,
                'queries': queries_for_this_row,
                'context': context
            })
            
    unique_queries = list(unique_queries)
    print(f"총 {len(unique_queries)} 개의 고유 검색어(Search Query) 임베딩 생성 중...")
    
    embeddings = embedding_service.embed_batch(unique_queries)
    emb_dict = {q: emb for q, emb in zip(unique_queries, embeddings)}
    
    print("Neo4j 벡터 DB 검색 및 Reranking 진행 중...")
    new_rows = []
    
    # 벡터 검색 (R&N_MDL 제외, 후보 50개 추출)
    # Reranking을 위해 Equipment/System/Building/Study-Survey 속성을 가져옵니다.
    query = """
    CALL db.index.vector.queryNodes("test_mdl_document_vector_idx", 50, $embedding)
    YIELD node, score
    WHERE NOT (node.source_file CONTAINS "R&N_MDL")
    RETURN node.source_file AS source_file, 
           node.title AS title, 
           node.system AS system, 
           node.equipment AS equipment, 
           node.building AS building,
           node.study_survey AS study_survey,
           score
    """
    
    for item in tqdm(section_queries):
        all_section_candidates = [] # 현재 섹션(행)의 모든 키워드에 대한 후보를 모음
        context = item['context']
        
        # 중복 문서 방지를 위한 Set
        seen_docs = set()
        
        for q_dict in item['queries']:
            search_query = q_dict['search_query']
            emb = emb_dict[search_query]
            
            with conn.session() as session:
                result = session.run(query, embedding=emb)
                candidates = [record for record in result]
                
            # Reranking 로직 적용
            reranked_candidates = []
            for c in candidates:
                base_score = c['score']
                bonus = 0.0
                
                bonus = add_scope_bonus(c, search_query, q_dict['keyword'])
                        
                final_score = base_score + bonus
                
                c_dict = {
                    'source_file': c['source_file'],
                    'title': c['title'],
                    'base_score': base_score,
                    'final_score': final_score,
                    'system': c['system'],
                    'equipment': c['equipment'],
                    'building': c['building'],
                    'study_survey': c['study_survey']
                }
                reranked_candidates.append(c_dict)
                
            # 각 키워드별로 최종 점수 기준 내림차순 정렬
            reranked_candidates.sort(key=lambda x: x['final_score'], reverse=True)
            
            # 한 개의 키워드 당 고유한 문서 20개를 찾아서 매칭 풀에 추가
            added_for_this_keyword = 0
            for c in reranked_candidates:
                doc_identifier = f"{c['source_file']}_{c['title']}"
                
                # 아직 이 섹션에 추가되지 않은 문서만 추가 (중복 문서 제거)
                if doc_identifier not in seen_docs:
                    seen_docs.add(doc_identifier)
                    all_section_candidates.append(c)
                    added_for_this_keyword += 1
                    
                # 20개의 고유 문서를 다 찾았으면 다음 키워드로 넘어감
                if added_for_this_keyword >= 20:
                    break
        
        # 섹션 내에서 모인 모든 문서들을 다시 최종 점수순으로 정렬
        all_section_candidates.sort(key=lambda x: x['final_score'], reverse=True)
        
        # 최종적으로 섹션당 상위 20개 추출
        top_20_for_section = all_section_candidates[:20]
        
        # 새 행 구성
        row = item['original_row'].to_dict()
        row['Depth_Context'] = context
        row['Search_Queries'] = ", ".join([q['search_query'] for q in item['queries']])
        
        for i in range(20):
            col_name = f"Matched_Doc_{i+1}"
            if i < len(top_20_for_section):
                c = top_20_for_section[i]
                proj = str(c['source_file']).replace('_MDL.xlsx', '').replace('_classified.csv', '').replace('.xlsx', '')
                # 어떤 이유로 점수가 올랐는지 알기 쉽도록 base_score와 final_score 함께 표기
                row[col_name] = f"[{proj}] {c['title']} (최종점수: {c['final_score']:.4f} / 기본: {c['base_score']:.4f})"
            else:
                row[col_name] = ""
                
        new_rows.append(row)
        
    # 데이터프레임 저장
    base_cols = [
        'Document', 'Page', '1st Depth', '2nd Depth', '3rd Depth', '4th Depth',
        '5th Depth', 'Depth_Context', 'Keywords', 'Search Query', 'Search_Queries', 'Chunk Text'
    ]
    match_cols = [f"Matched_Doc_{i+1}" for i in range(20)]
    
    result_df = pd.DataFrame(new_rows)
    final_cols = [c for c in base_cols if c in result_df.columns] + match_cols
    result_df = result_df[final_cols]
    
    result_df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"\n성공적으로 저장되었습니다: {output_path}")

def main():
    embedding_service = UnifiedEmbeddingService.build_default()
    conn = Neo4jConnection()
    conn.connect()
    
    files_to_process = [
        {
            "in": str(OUTPUT_DIR / "output_itb_section6_focused.csv"),
            "out": str(OUTPUT_DIR / "output_match_all_projects_section6.csv")
        },
        {
            "in": str(OUTPUT_DIR / "output_itb_section7_focused.csv"),
            "out": str(OUTPUT_DIR / "output_match_all_projects_section7.csv")
        }
    ]
    
    try:
        for f in files_to_process:
            if os.path.exists(f["in"]):
                process_file(f["in"], f["out"], embedding_service, conn)
            else:
                print(f"[경고] 입력 파일을 찾을 수 없습니다: {f['in']}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
