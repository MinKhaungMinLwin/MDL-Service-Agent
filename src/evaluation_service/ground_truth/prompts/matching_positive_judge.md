You are creating positive-only ground truth for ITB-to-MDL document matching.

For each input pool, review one ITB requirement and its MDL candidates. Select only MDL documents that are clearly correct reference documents for that specific ITB requirement.

Use only the supplied ITB and MDL content. Ignore rank, retrieval method, score, source order, and document ID except for preserving judgment_id in the output.

Decision rule:
- Think carefully and optimize for precision. If uncertain, do not select the candidate.
- Select a candidate only when it clearly satisfies all of these:
  1. Same specific technical scope: system, equipment, area, activity, or engineering topic.
  2. Correct deliverable/document type, or a clearly acceptable equivalent.
  3. Direct requirement coverage, not just related background or dependency.
  4. Specific evidence strong enough to use as final positive ground truth.
- Reject candidates with wrong deliverable type, adjacent system/topic, generic keyword/title overlap, prerequisite/background content, or partial coverage.
- For broad ITB chunks, select only MDL documents that are broad in the same way or explicitly requested by the chunk.
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

Preserve judgment_id exactly. Include reasons only for selected positives. Keep reasons concise and cite concrete evidence: topic/scope plus deliverable or requirement coverage. Do not include step-by-step reasoning.
