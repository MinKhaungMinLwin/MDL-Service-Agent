You are creating positive-only ground truth for ITB-to-MDL document matching.

For each input pool, review the supplied ITB requirement and MDL candidates. Select only MDL documents that are direct correct reference documents for the ITB requirement.

Use only the supplied ITB and MDL content. Do not infer relevance from rank, retrieval method, score, source order, or document ID.

Selection standard:
- Prefer precision over recall.
- Select a candidate only when all of these are true:
  1. It matches the ITB technical topic, system, equipment, area, or activity at a specific level.
  2. Its deliverable/document type is the same as, or clearly acceptable for, the ITB requirement.
  3. Its content directly covers the requirement, not merely a nearby dependency or background topic.
  4. It would be safe to use as a positive ground-truth answer for this ITB chunk.
- A shared discipline, package, equipment name, area, or generic keyword is not enough.
- Reject wrong deliverable types even when the technical topic is similar.
- Reject adjacent context, background information, partial dependencies, generic standards, and documents that only explain prerequisites.
- For broad or generic ITB chunks, select a candidate only when the MDL evidence is clearly direct and specific.
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
