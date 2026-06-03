You are verifying high-precision ITB-to-MDL ground-truth judgments.

Review each supplied judgment against its embedded ITB and MDL content. Decide whether the proposed relevance-3 positive label is defensible under a precision-first standard.

Use only the supplied ITB and MDL content. Ignore rank, retrieval method, score, source order, and document ID except for preserving judgment_id in the output.

Verification standard:
- Agree only when the proposed relevance-3 positive label is clearly supported by evidence.
- For relevance 3, all checks must pass:
  1. Technical scope: same specific system, equipment, area, activity, or engineering topic as the ITB chunk.
  2. Deliverable fit: same deliverable/document type requested by the ITB, or a clearly acceptable equivalent.
  3. Requirement coverage: the MDL content directly answers, supports, or is the requested document for the ITB requirement.
  4. Context fit: the match is not just a nearby dependency, prerequisite, background document, or generic discipline/package reference.
  5. Evidence quality: the supplied content is specific enough that this pair is safe to keep as final positive ground truth.
- If any required check is uncertain, relevance 3 is not defensible.
- If the MDL is adjacent, generic, background context, a prerequisite, a partial dependency, an adjacent system, or the wrong deliverable type, do not return relevance 3.
- For broad ITB chunks, relevance 3 requires the MDL document to be broad in the same way or explicitly requested by the chunk.
- Set agrees to true only when relevance 3 is defensible. If relevance 3 is not defensible, set agrees to false and return the corrected relevance.

Return strict JSON:
{
  "results": [
    {
      "judgment_id": "...",
      "relevance": 0,
      "agrees": true,
      "reason": "..."
    }
  ]
}

Preserve judgment_id exactly. Use relevance scores from 0 to 3. Each reason must cite the concrete evidence or the specific mismatch. Keep reasons concise.
