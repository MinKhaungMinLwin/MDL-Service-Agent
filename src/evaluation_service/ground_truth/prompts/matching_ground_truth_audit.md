You are auditing positive ground truth for ITB-to-MDL document matching.

Review each supplied positive ground-truth row against its embedded ITB and MDL content. Decide whether the row is safe to keep as a final positive label.

Use only the supplied ITB and MDL content. Ignore rank, retrieval method, score, source order, and document ID except for preserving judgment_id in the output.

Audit standard:
- Return "ok" only when all checks pass:
  1. Technical scope: same specific system, equipment, area, activity, or engineering topic as the ITB chunk.
  2. Deliverable fit: same deliverable/document type requested by the ITB, or a clearly acceptable equivalent.
  3. Requirement coverage: the MDL content directly answers, supports, or is the requested document for the ITB requirement.
  4. Context fit: the match is not just a nearby dependency, prerequisite, background document, or generic discipline/package reference.
  5. Evidence quality: the supplied content is specific enough that this pair is safe to keep as final positive ground truth.
- Return "suspicious" when the pair may be relevant but evidence is incomplete, too broad, too generic, partially aligned, or missing a clear deliverable/coverage signal.
- Return "remove" when the pair is clearly not a direct positive match, has the wrong deliverable type, concerns an adjacent system/topic, only shares generic keywords, or only provides prerequisite/background context.
- For broad ITB chunks, "ok" requires the MDL document to be broad in the same way or explicitly requested by the chunk. Otherwise use "suspicious" or "remove" depending on the evidence.

Return strict JSON:
{
  "results": [
    {
      "judgment_id": "...",
      "audit_status": "ok",
      "audit_relevance": 3,
      "reason": "concise evidence for the audit decision"
    }
  ]
}

Preserve judgment_id exactly. Use audit_status only from ok, suspicious, or remove. Use audit_relevance from 0 to 3. Each reason must cite the concrete evidence or the specific mismatch. Keep reasons concise.
