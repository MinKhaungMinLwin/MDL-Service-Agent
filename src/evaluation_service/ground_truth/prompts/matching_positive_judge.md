You are creating positive-only ground truth for ITB-to-MDL document matching.

For each input pool, review the supplied ITB requirement and MDL candidates. Select only MDL documents that are direct correct reference documents for the ITB requirement.

Use only the supplied ITB and MDL content. Do not infer relevance from rank, retrieval method, score, source order, or document ID.

Selection standard:
- Prefer precision over recall.
- Select a candidate only when it has a direct technical topic match, appropriate deliverable/document type, and clear requirement coverage.
- A shared discipline, equipment name, area, or generic keyword is not enough.
- Do not select adjacent context, background information, partial dependencies, or wrong deliverable types.
- If no candidate is a direct positive match, return an empty positive_judgment_ids list.

Return strict JSON:
{
  "results": [
    {
      "section": "...",
      "chunk_id": "...",
      "positive_judgment_ids": ["..."],
      "reasons": {
        "judgment_id": "concise evidence for selecting this candidate"
      }
    }
  ]
}

Preserve judgment_id exactly. Include reasons only for selected positives. Keep reasons concise and evidence-based.
