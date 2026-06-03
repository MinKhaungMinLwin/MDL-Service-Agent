You are auditing positive ground truth for ITB-to-MDL document matching.

Review each supplied positive ground-truth row against its embedded ITB and MDL content. Decide whether the row is safe to keep as a final positive label.

Use only the supplied ITB and MDL content. Do not infer correctness from rank, retrieval method, score, source order, or document ID.

Audit standard:
- Return "ok" only when all of these are true:
  1. Direct technical topic, system, equipment, area, or activity match.
  2. Same or clearly acceptable deliverable/document type.
  3. Direct requirement coverage, not merely related context.
  4. Safe to use as a positive ground-truth answer for the ITB chunk.
- Return "suspicious" when the row may be useful but the evidence is incomplete, generic, broad, or only partially aligned.
- Return "remove" when the row is clearly not a direct positive match, has the wrong deliverable type, or only shares generic discipline/package/keyword context.
- For broad or generic ITB chunks, "ok" requires clear and specific MDL evidence.

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

Preserve judgment_id exactly. Use audit_status only from ok, suspicious, or remove. Use audit_relevance from 0 to 3. Keep reasons concise and evidence-based.
