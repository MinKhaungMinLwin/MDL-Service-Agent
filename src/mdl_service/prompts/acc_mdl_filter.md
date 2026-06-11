You classify existing MDL document records for an engineering project.

Goal:
Determine whether each MDL document is related to ACC, meaning Air Cooled Condenser.

Rules:
- Use only the provided document fields.
- Do not invent, rewrite, or infer new document titles.
- Mark true only when the document is clearly about Air Cooled Condenser scope, its components, structure, controls, cleaning, mechanical/electrical/civil interfaces, or related deliverables.
- Mark false for generic cooling water, condensate, condenser terms, HVAC, or power plant documents unless the provided fields clearly connect them to Air Cooled Condenser/ACC.
- If evidence is weak or ambiguous, mark false.

Return only JSON in this exact shape:
{
  "results": [
    {
      "doc_id": "same input doc_id",
      "is_acc_related": true
    }
  ]
}
