You are verifying high-precision ITB-to-MDL ground-truth judgments.

For each verification pool, review one ITB requirement and its proposed positive MDL candidates. Decide whether each proposed relevance-3 positive label is defensible under a precision-first standard.

Use only the supplied ITB and MDL content. Ignore rank, retrieval method, score, source order, and document ID except for preserving judgment_id in the output.

Verification standard:
- Think carefully and verify independently. Do not agree just because the judge selected the candidate.
- Set agrees=true only when relevance 3 clearly satisfies all of these:
  1. Same specific technical scope: system, equipment, area, activity, or engineering topic.
  2. Correct deliverable/document type, or a clearly acceptable equivalent.
  3. Direct requirement coverage, not just related background or dependency.
  4. Specific evidence strong enough to keep as final positive ground truth.
- If any check is uncertain, set agrees=false and return the corrected relevance.
- Do not return relevance 3 for wrong deliverable type, adjacent system/topic, generic keyword/title overlap, prerequisite/background content, or partial coverage.
- For broad ITB chunks, relevance 3 requires the MDL document to be broad in the same way or explicitly requested by the chunk.

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

Preserve each positive candidate judgment_id exactly. Return one result per positive candidate. Use relevance scores from 0 to 3. Keep reasons concise and cite concrete evidence or the specific mismatch. Do not include step-by-step reasoning.
