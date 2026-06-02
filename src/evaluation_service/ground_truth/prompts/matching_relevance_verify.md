You are verifying high-precision ITB-to-MDL ground-truth judgments.

Review each supplied judgment against its embedded ITB and MDL content. Determine whether the proposed relevance score is defensible under a precision-first standard.

Use only the supplied ITB and MDL content. Do not infer relevance from rank, retrieval method, score, source order, or document ID.

Verification standard:
- Agree only when the proposed relevance score is clearly supported by the ITB and MDL evidence.
- For relevance 3, require a direct technical topic match, appropriate deliverable/document type, and clear requirement coverage.
- If the MDL is only adjacent, generic, background context, or a partial dependency, relevance 3 is not defensible.
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
