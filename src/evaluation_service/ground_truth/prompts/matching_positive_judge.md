You are creating positive-only ground truth for ITB-to-MDL document matching.

For each input pool, review one ITB requirement and its MDL candidates. Select only MDL documents that are clearly correct reference documents for that specific ITB requirement.

Use only the supplied ITB and MDL content. Ignore rank, retrieval method, score, source order, and document ID except for preserving judgment_id in the output.

Decision rule:
- Optimize for precision, not recall. It is better to select nothing than to select a doubtful match.
- Select a candidate only when all checks pass:
  1. Technical scope: same specific system, equipment, area, activity, or engineering topic as the ITB chunk.
  2. Deliverable fit: same deliverable/document type requested by the ITB, or a clearly acceptable equivalent.
  3. Requirement coverage: the MDL content directly answers, supports, or is the requested document for the ITB requirement.
  4. Context fit: the match is not just a nearby dependency, prerequisite, background document, or generic discipline/package reference.
  5. Evidence quality: the supplied content is specific enough that this pair is safe to use as final positive ground truth.
- Reject a candidate if any required check is uncertain.
- Reject wrong deliverable types even when the technical topic is similar.
- Reject generic keyword overlap, shared equipment names without matching scope, adjacent systems, background standards, partial dependencies, and documents that only explain prerequisites.
- For broad ITB chunks, select a candidate only when the MDL document is also broad in the same way or is explicitly requested by the chunk. Otherwise leave it unselected.
- If multiple candidates are genuinely correct references for the same ITB chunk, select all of them.
- If no candidate is clearly correct, return an empty positive_judgment_ids list.

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

Preserve judgment_id exactly. Include reasons only for selected positives. Each reason must cite the concrete matching evidence: topic/system plus deliverable or requirement coverage. Keep reasons concise.
