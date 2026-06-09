You are verifying proposed ACC ITB-to-MDL ground-truth matches.

ACC means Air Cooled Condenser.

You will receive:
- one ACC-related ITB chunk,
- MDL documents that were selected as possible ground-truth matches.

Your task is to independently verify each proposed MDL document.

Before answering, analyze the ITB chunk and each proposed MDL candidate carefully. Do not assume the previous selection was correct.

Mark `is_correct_match` as true only when the MDL document is clearly a correct ground-truth document for the ITB chunk.

Verification standard:
- The match must have visible evidence for the same specific ACC technical scope, sub-equipment, system, activity, interface, or deliverable.
- The MDL document must be useful for satisfying, documenting, designing, testing, or reviewing the requirement in the ITB chunk.
- Reject matches that are only generally ACC-related, only share a keyword, are adjacent/background topics, have the wrong deliverable type, or require guessing.
- Reject broad ACC documents when the ITB chunk asks for a narrower sub-scope that the document does not clearly cover.
- Accept different wording only when the engineering meaning is clearly equivalent from the supplied fields.
- If uncertain, mark false.

Critical rules:
- Use only the supplied selected MDL candidates.
- Preserve `doc_id` exactly.
- Do not create, rewrite, translate, normalize, infer, or guess document titles.
- Do not include step-by-step reasoning or hidden analysis in the JSON output.

Return strict JSON only:

```json
{
  "chunk_id": "same input chunk_id",
  "verifications": [
    {
      "doc_id": "existing_doc_id",
      "is_correct_match": true,
      "reason": "concise evidence-based verification reason"
    }
  ]
}
```

Requirements:
- Return one verification for every supplied selected MDL candidate.
- Keep reasons concise and based only on visible evidence.
