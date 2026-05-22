import os
import pandas as pd
from tqdm import tqdm
import re

from mdl_runtime.config import OUTPUT_DIR
from mdl_runtime.neo4j_connection import Neo4jConnection
from mdl_runtime.embeddings import UnifiedEmbeddingService

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def clean_depth_text(text):
    if not isinstance(text, str) or text == 'nan':
        return ""
    # "6.1.1 " 같은 숫자 번호 매기기 제거 및 밑줄(_)을 공백으로 변경
    cleaned = re.sub(r'^[\d\.]+\s*', '', text)
    cleaned = cleaned.replace('_', ' ')
    return cleaned.strip()

def get_depth_context(row):
    """1~4 Depth에서 가장 하위 Depth의 핵심 단어를 추출합니다."""
    for depth in ['4th Depth', '3rd Depth', '2nd Depth', '1st Depth']:
        val = str(row.get(depth, ''))
        if val != 'nan' and val.strip():
            return clean_depth_text(val)
    return ""

def process_file(csv_path, output_path, embedding_service, conn):
    print(f"\n입력 파일 읽는 중: {csv_path}")
    df = pd.read_csv(csv_path)
    
    # R&N ITB의 섹션 6과 7에 해당하는 데이터만 필터링 (번호가 생략된 텍스트 추출 형태도 포함)
    valid_starts = ('6.', '7.', '6_', '7_', 'design and operational', 'scope of')
    target_df = df[df['1st Depth'].astype(str).str.lower().str.startswith(valid_starts)].copy()
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
            
        context = get_depth_context(row)
        individual_keywords = [k.strip() for k in kw_str.split(',') if k.strip()]
        
        queries_for_this_row = []
        for kw in individual_keywords:
            search_query = f"{context} {kw}".strip()
            unique_queries.add(search_query)
            queries_for_this_row.append({
                'keyword': kw,
                'search_query': search_query
            })
            
        if queries_for_this_row:
            section_queries.append({
                'original_row': row,
                'queries': queries_for_this_row,
                'context': context
            })
            
    unique_queries = list(unique_queries)
    print(f"총 {len(unique_queries)} 개의 고유 검색어(Context+Keyword) 임베딩 생성 중...")
    
    embeddings = embedding_service.embed_batch(unique_queries)
    emb_dict = {q: emb for q, emb in zip(unique_queries, embeddings)}
    
    print("Neo4j 벡터 DB 검색 및 Reranking 진행 중...")
    new_rows = []
    
    # 벡터 검색 (R&N_MDL 제외, 후보 50개 추출)
    # Reranking을 위해 system, equipment 속성도 가져옵니다.
    query = """
    CALL db.index.vector.queryNodes("test_mdl_document_vector_idx", 50, $embedding)
    YIELD node, score
    WHERE toLower(node.source_file) CONTAINS "fadhili"
    RETURN node.source_file AS source_file, 
           node.title AS title, 
           node.system AS system, 
           node.equipment AS equipment, 
           score
    """
    
    for item in tqdm(section_queries):
        all_section_candidates = [] # 현재 섹션(행)의 모든 키워드에 대한 후보를 모음
        context = item['context']
        context_lower = context.lower()
        
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
                
                sys_val = str(c['system']).lower() if c['system'] else ""
                equip_val = str(c['equipment']).lower() if c['equipment'] else ""
                
                search_query_lower = search_query.lower()
                keyword_lower = q_dict['keyword'].lower()
                
                # Equipment Match 가중치 (+0.20)
                if equip_val and len(equip_val) > 2:
                    if (equip_val in context_lower or context_lower in equip_val or 
                        equip_val in keyword_lower or keyword_lower in equip_val):
                        bonus += 0.20
                        
                # System Match 가중치 (+0.10)
                if sys_val and len(sys_val) > 2:
                    if (sys_val in context_lower or context_lower in sys_val or 
                        sys_val in keyword_lower or keyword_lower in sys_val):
                        bonus += 0.10
                        
                final_score = base_score + bonus
                
                c_dict = {
                    'source_file': c['source_file'],
                    'title': c['title'],
                    'base_score': base_score,
                    'final_score': final_score,
                    'system': c['system'],
                    'equipment': c['equipment']
                }
                reranked_candidates.append(c_dict)
                
            # 각 키워드별로 최종 점수 기준 내림차순 정렬
            reranked_candidates.sort(key=lambda x: x['final_score'], reverse=True)
            
            # 한 개의 키워드 당 고유한 문서 3개를 찾아서 매칭 풀에 추가
            added_for_this_keyword = 0
            for c in reranked_candidates:
                doc_identifier = f"{c['source_file']}_{c['title']}"
                
                # 아직 이 섹션에 추가되지 않은 문서만 추가 (중복 문서 제거)
                if doc_identifier not in seen_docs:
                    seen_docs.add(doc_identifier)
                    all_section_candidates.append(c)
                    added_for_this_keyword += 1
                    
                # 3개의 고유 문서를 다 찾았으면 다음 키워드로 넘어감
                if added_for_this_keyword >= 3:
                    break
        
        # 섹션 내에서 모인 모든 문서(각 키워드별 Top 3 문서들의 합합)들을 다시 최종 점수순으로 정렬
        all_section_candidates.sort(key=lambda x: x['final_score'], reverse=True)
        
        # 최종적으로 섹션당 상위 10개 추출
        top_10_for_section = all_section_candidates[:10]
        
        # 새 행 구성
        row = item['original_row'].to_dict()
        row['Depth_Context'] = context
        row['Search_Queries'] = ", ".join([q['search_query'] for q in item['queries']])
        
        for i in range(10):
            col_name = f"Matched_Doc_{i+1}"
            if i < len(top_10_for_section):
                c = top_10_for_section[i]
                proj = str(c['source_file']).replace('_MDL.xlsx', '').replace('_classified.csv', '').replace('.xlsx', '')
                # 어떤 이유로 점수가 올랐는지 알기 쉽도록 base_score와 final_score 함께 표기
                row[col_name] = f"[{proj}] {c['title']} (최종점수: {c['final_score']:.4f} / 기본: {c['base_score']:.4f})"
            else:
                row[col_name] = ""
                
        new_rows.append(row)
        
    # 데이터프레임 저장
    base_cols = ['Document', 'Page', '1st Depth', '2nd Depth', '3rd Depth', '4th Depth', 'Depth_Context', 'Keywords', 'Search_Queries', 'Chunk Text']
    match_cols = [f"Matched_Doc_{i+1}" for i in range(10)]
    
    result_df = pd.DataFrame(new_rows)
    final_cols = [c for c in base_cols if c in result_df.columns] + match_cols
    result_df = result_df[final_cols]
    
    result_df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"\n성공적으로 저장되었습니다: {output_path}")

def main():
    embedding_service = UnifiedEmbeddingService.build_default()
    conn = Neo4jConnection()
    conn.connect()
    
    # current_test_env 폴더 내의 새 추출물 사용
    files_to_process = [
        {
            "in": str(OUTPUT_DIR / "output_itb_section7_focused.csv"),
            "out": str(OUTPUT_DIR / "output_match_fadhili_only_section7.csv")
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
