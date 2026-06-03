You are verifying high-precision ITB-to-MDL ground-truth judgments.

Review each supplied judgment against its embedded ITB and MDL content. Determine whether the proposed relevance score is defensible under a precision-first standard.

Use only the supplied ITB and MDL content. Do not infer relevance from rank, retrieval method, score, source order, or document ID.

Verification standard:
- Agree only when the proposed relevance score is clearly supported by the ITB and MDL evidence.
- For relevance 3, require all of these:
  1. Direct technical topic, system, equipment, area, or activity match.
  2. Same or clearly acceptable deliverable/document type.
  3. Direct requirement coverage, not merely related context.
  4. Safe to use as a positive ground-truth answer for the ITB chunk.
- If the MDL is only adjacent, generic, background context, a prerequisite, a partial dependency, or the wrong deliverable type, relevance 3 is not defensible.
- For broad or generic ITB chunks, relevance 3 requires clear and specific MDL evidence.
- If the proposed score is too high or too low, set agrees to false and return the corrected relevance.

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

Preserve judgment_id exactly. Use relevance scores from 0 to 3. Keep each reason concise and evidence-based.
