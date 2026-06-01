You are verifying ITB-to-MDL relevance judgments.

Review each supplied judgment against its embedded ITB and MDL content. Determine whether the proposed relevance score is defensible.
Return strict JSON:
{
  "results": [
    {
      "judgment_id": "...",
      "relevance": 0,
      "confidence": 0.0,
      "agrees": true,
      "reason": "..."
    }
  ]
}

Preserve judgment_id exactly. Use relevance scores from 0 to 3. Keep each reason concise.
