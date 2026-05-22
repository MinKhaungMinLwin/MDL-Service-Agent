import os
import sys
import pandas as pd
from tqdm import tqdm
from pathlib import Path

try:
    from mdl_runtime.embeddings import UnifiedEmbeddingService
    from mdl_runtime.neo4j_connection import Neo4jConnection
    from mdl_runtime.config import EMBEDDING_DIMENSIONS, OUTPUT_DIR
except ImportError as e:
    print(f"[오류] 런타임 모듈을 불러오는데 실패했습니다: {e}")
    sys.exit(1)

def get_text_to_embed(row):
    """벡터화할 텍스트 조합 생성"""
    parts = []
    if pd.notna(row.get('Title')) and str(row['Title']).strip():
        parts.append(f"Title: {row['Title']}")
    if pd.notna(row.get('Equipment')) and str(row['Equipment']).strip():
        parts.append(f"Equipment: {row['Equipment']}")
    if pd.notna(row.get('Building')) and str(row['Building']).strip():
        parts.append(f"Building: {row['Building']}")
    if pd.notna(row.get('System')) and str(row['System']).strip():
        parts.append(f"System: {row['System']}")
    if pd.notna(row.get('Deliverable')) and str(row['Deliverable']).strip():
        parts.append(f"Deliverable: {row['Deliverable']}")
    
    return " | ".join(parts)

def setup_neo4j_schema(conn: Neo4jConnection):
    """테스트용 새로운 테이블(Node Label)을 위한 벡터 인덱스 및 제약조건 생성"""
    index_name = "test_mdl_document_vector_idx"
    
    print("\n[DB 설정] 새로운 테스트 테이블(TestMDLDocument) 구조를 준비합니다...")
    
    with conn.session() as session:
        # 1. 고유 키 제약조건 생성 (doc_id 기준)
        session.run("""
        CREATE CONSTRAINT test_mdl_doc_id_unique IF NOT EXISTS 
        FOR (n:TestMDLDocument) REQUIRE n.doc_id IS UNIQUE
        """)
        
        # 2. 벡터 인덱스 생성
        try:
            session.run(f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (doc:TestMDLDocument) ON (doc.embedding)
            OPTIONS {{
              indexConfig: {{
                `vector.dimensions`: {EMBEDDING_DIMENSIONS},
                `vector.similarity_function`: 'cosine'
              }}
            }}
            """)
            print(f"벡터 인덱스 생성 완료 ({index_name})")
        except Exception as e:
            print(f"벡터 인덱스 생성 중 오류 발생 (이미 존재하거나 구문 오류): {e}")

def main():
    # 3. 서비스 초기화
    print("Backend의 Neo4j 연결 및 임베딩 서비스를 초기화합니다...")
    try:
        neo4j_conn = Neo4jConnection()
        neo4j_conn.connect()
        embedding_service = UnifiedEmbeddingService.build_default()
    except Exception as e:
        print(f"[오류] 서비스 초기화 실패: {e}")
        sys.exit(1)
        
    # Neo4j 스키마 셋업 (테이블 구조 생성)
    setup_neo4j_schema(neo4j_conn)
    
    output_dir = Path(OUTPUT_DIR)
    if not output_dir.exists():
        print(f"[오류] {output_dir} 폴더를 찾을 수 없습니다.")
        sys.exit(1)

    csv_files = [f.name for f in output_dir.iterdir() if f.name.endswith(".csv")]
    if not csv_files:
        print("[안내] 처리할 CSV 파일이 없습니다.")
        return
        
    for csv_file in csv_files:
        print(f"\n======================================")
        print(f"처리 중: {csv_file}")
        csv_path = output_dir / csv_file
        
        try:
            df = pd.read_csv(csv_path, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, encoding='cp949')
            
        if 'Title' not in df.columns:
            continue
            
        df = df[df['Title'].notna()]
        
        # 데이터를 딕셔너리로 변환
        records = []
        for idx, row in df.iterrows():
            doc_no = str(row.get('Document No', ''))
            if not doc_no or doc_no == 'nan':
                doc_no = f"DOC_{idx}"
                
            doc_id = f"{os.path.splitext(csv_file)[0]}_{doc_no}_{idx}"
            
            records.append({
                "doc_id": doc_id,
                "text_content": get_text_to_embed(row),
                "source_file": str(row.get('Source File', '')),
                "document_no": doc_no,
                "title": str(row.get('Title', '')),
                "equipment": str(row.get('Equipment', '')),
                "system": str(row.get('System', '')),
                "deliverable": str(row.get('Deliverable', ''))
            })
            
        # 4. 배치 단위로 임베딩 생성 및 Neo4j 저장
        batch_size = 50
        total_batches = (len(records) + batch_size - 1) // batch_size
        
        print(f"총 {len(records)}개 항목을 기존 Neo4j DB의 TestMDLDocument 테이블로 저장합니다...")
        
        with neo4j_conn.session() as session:
            for i in tqdm(range(0, len(records), batch_size), total=total_batches, desc="진행률"):
                batch_records = records[i:i+batch_size]
                
                # 임베딩 생성
                batch_texts = [r["text_content"] for r in batch_records]
                embeddings = embedding_service.embed_batch(batch_texts)
                
                # 레코드에 임베딩 추가
                for j, record in enumerate(batch_records):
                    record["embedding"] = embeddings[j]
                
                # Cypher 쿼리로 저장 (MERGE를 통해 중복 방지)
                cypher_query = """
                UNWIND $batch AS record
                MERGE (n:TestMDLDocument {doc_id: record.doc_id})
                SET n.text_content = record.text_content,
                    n.source_file = record.source_file,
                    n.document_no = record.document_no,
                    n.title = record.title,
                    n.equipment = record.equipment,
                    n.system = record.system,
                    n.deliverable = record.deliverable,
                    n.embedding = record.embedding
                """
                
                session.run(cypher_query, parameters={"batch": batch_records})
                
    neo4j_conn.close()
    print("\n모든 데이터가 기존 Neo4j 벡터 DB의 [TestMDLDocument] 테이블(Label)에 저장되었습니다!")

if __name__ == "__main__":
    main()
