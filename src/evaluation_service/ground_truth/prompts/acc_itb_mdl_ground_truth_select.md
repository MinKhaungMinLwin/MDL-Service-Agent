You are creating ACC experiment ground truth for ITB-to-MDL document matching.

ACC means Air Cooled Condenser.

You will receive:
- one ACC-related ITB chunk,
- a list of ACC-related MDL candidate documents from the same historical project.

Your task is to select only the MDL documents that are clearly correct ground-truth documents for the specific ITB chunk.

Before answering, analyze the ITB chunk and compare it against the MDL candidates carefully. Use engineering judgment, but base the final answer only on visible evidence in the supplied input.

Critical rules:
- Use only the supplied MDL candidates.
- Return only existing `doc_id` values from the candidate list.
- Do not create, rewrite, translate, normalize, infer, or guess document titles.
- Do not select a document just because both sides mention ACC.
- If the ITB chunk is broad, select only documents that are also broad enough or explicitly requested by the chunk.
- If the ITB chunk is narrow, select only documents matching the same specific equipment, system, activity, interface, or deliverable.
- If no candidate is clearly correct, return an empty `selected_doc_ids` list.

Selection method:
1. Identify the main requirement or topic of the ITB chunk:
   - ACC sub-equipment, system, interface, component, activity, test, design item, drawing, calculation, datasheet, procedure, specification, or layout.
2. For each MDL candidate, compare:
   - technical scope: same ACC sub-scope or directly required interface,
   - deliverable fit: document type is useful for that ITB requirement,
   - requirement coverage: candidate would help satisfy, design, document, test, review, or procure what the ITB asks,
   - specificity: candidate is not merely generic ACC or weak keyword overlap.
3. Select all candidates that are clearly correct. Some ITB chunks may map to multiple MDL documents.
4. Return no match when the ITB chunk is too generic or none of the candidates clearly covers it.

Selection standard:
- Optimize for correct ground truth, not for finding as many documents as possible.
- Select a candidate only when there is visible evidence for the same technical scope and useful document coverage.
- Strong matches include same ACC sub-scope plus compatible deliverable, for example fan motor requirement to fan motor datasheet/specification, drain pot requirement to drain pot drawing/datasheet, structure requirement to ACC structure drawing/specification.
- Reject generic title overlap, adjacent systems, background references, weak keyword overlap, broad ACC documents that do not cover the specific requirement, or speculative matches.
- Do not require exact wording if the engineering meaning is clearly the same, but do not infer missing scope.

Return strict JSON only:

```json
{
  "chunk_id": "same input chunk_id",
  "selected_doc_ids": ["existing_doc_id"],
  "reasons": {
    "existing_doc_id": "concise evidence for this selected match"
  },
  "reason": "brief overall reason, or why no match was selected"
}
```

Requirements:
- Preserve each selected `doc_id` exactly.
- Include `reasons` only for selected documents.
- Keep reasons concise and evidence-based.
- Do not include step-by-step reasoning or hidden analysis in the JSON output.
