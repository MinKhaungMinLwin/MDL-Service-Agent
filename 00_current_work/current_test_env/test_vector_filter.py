from mdl_runtime.neo4j_connection import Neo4jConnection
from mdl_runtime.embeddings import UnifiedEmbeddingService

embedding_service = UnifiedEmbeddingService.build_default()
emb = embedding_service.embed_batch(['DESIGN AND OPERATIONAL REQUIREMENTS GNCPC 1800 MW Net'])[0]

query = '''
CALL db.index.vector.queryNodes("test_mdl_document_vector_idx", 50, $embedding)
YIELD node, score
WHERE NOT (node.source_file CONTAINS "R&N_MDL")
RETURN count(node)
'''

conn = Neo4jConnection()
conn.connect()
with conn.session() as session:
    res = session.run(query, embedding=emb)
    count = res.single()[0]
    print(f'Filtered results from top 50: {count}')
conn.close()
