You are creating high-precision ground truth for ITB-to-MDL document matching.

For every MDL candidate in each input pool, judge whether the MDL document should be treated as a correct reference document for the supplied ITB requirement.
Use only the supplied ITB and MDL content. Do not infer relevance from rank, retrieval method, score, source order, or document ID.

Decision standard:
- Prefer precision over recall. Do not mark a candidate as strongly relevant unless the MDL content clearly supports the ITB requirement.
- A shared discipline, equipment name, area, or generic keyword is not enough for a strong match.
- The MDL should match the requested technical topic and the expected deliverable/document type.
- If the MDL only provides adjacent information, background context, generic data, or a partial dependency, score it 2 or lower.
- If the ITB requirement is broad, score 3 only for MDL documents that are directly useful for producing or verifying that requirement.

Score each criterion from 0 to 3:
- topic_match: equipment, system, or technical topic alignment.
- deliverable_match: alignment of the requested and offered document type.
- requirement_coverage: how well the MDL document addresses the ITB requirement.
- context_fit: whether the MDL document is appropriate in the ITB context.

Assign one overall relevance:
- 3: strongly relevant; direct technical and deliverable match; safe to use as a positive ground-truth label.
- 2: partially relevant; useful context or related dependency, but not enough for a positive ground-truth label.
- 1: weakly related; same broad topic, area, equipment, or discipline, but insufficient or wrong deliverable.
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
      "reason": "..."
    }
  ]
}

Preserve judgment_id exactly. Keep each reason concise and evidence-based. In the reason, mention the strongest evidence for the score, especially whether the deliverable and requirement coverage are direct or only partial.
