You are assessing relevance for ITB-to-MDL document matching.

For every input pair, judge whether the MDL document is needed or useful for satisfying the ITB requirement.
Use only the supplied ITB and MDL content. Do not infer relevance from rank, retrieval method, or score.

Score each criterion from 0 to 3:
- topic_match: equipment, system, or technical topic alignment.
- deliverable_match: alignment of the requested and offered document type.
- requirement_coverage: how well the MDL document addresses the ITB requirement.
- context_fit: whether the MDL document is appropriate in the ITB context.

Assign one overall relevance:
- 3: strongly relevant; the MDL document is very likely required.
- 2: relevant; the MDL document is useful for the requirement.
- 1: weakly related; same topic but insufficient or wrong deliverable.
- 0: unrelated.

Return strict JSON:
{
  "results": [
    {
      "judgment_id": "...",
      "section": "...",
      "chunk_id": "...",
      "mdl_doc_id": "...",
      "topic_match": 0,
      "deliverable_match": 0,
      "requirement_coverage": 0,
      "context_fit": 0,
      "relevance": 0,
      "confidence": 0.0,
      "reason": "..."
    }
  ]
}

Preserve judgment_id exactly. Keep each reason concise and evidence-based.
