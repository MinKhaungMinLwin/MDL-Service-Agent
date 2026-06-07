You are filtering ITB requirement chunks for ACC scope.

ACC means Air Cooled Condenser.

For each ITB chunk, determine whether it has any signal related to Air Cooled Condenser scope.

Mark `is_acc_related` as true when the chunk contains any visible ACC-related signal, keyword, requirement, description, equipment, system, drawing, interface, or context. The goal is to keep potentially relevant chunks for later ground-truth review, so prefer recall over precision.

Keep the chunk when it mentions or strongly signals any of these topics:
- ACC or Air Cooled Condenser.
- ACC mechanical, civil/structural, electrical, instrumentation, control, performance, erection, testing, design, layout, interface, or commissioning scope.
- ACC fan, fan motor, fan deck, bundle, fin tube, wind wall, steam duct, exhaust steam duct, vacuum, air removal, ejector, hogging/holding system, condensate, drain, drain pot, hotwell, condensate pump pit, platform, access, foundation, structure, cable, lighting, instrument, control, or monitoring.
- A table/list/section where ACC appears as one item among other equipment.
- A chunk whose hierarchy, title, section path, keywords, or text includes ACC/Air Cooled Condenser even if the detailed text is short.

Mark false when:
- the chunk is generic project/admin/commercial text,
- the chunk has no visible ACC-related term, equipment, context, or signal,
- the chunk discusses generic cooling water, HVAC, condenser, condensate, vacuum, pumps, drains, structures, electrical, or instrumentation with no ACC-related signal anywhere in the provided fields.

Be inclusive. If there is any reasonable visible signal that the chunk may be useful for ACC ground-truth labeling, mark true. Only mark false when there is no ACC signal.

Return only JSON in this exact shape:

```json
{
  "results": [
    {
      "chunk_id": "string",
      "is_acc_related": true,
      "reason": "short evidence-based reason"
    }
  ]
}
```

Rules:
- Return one result for every input chunk.
- Use the original `chunk_id` exactly.
- Do not invent chunk IDs.
- Keep `reason` concise and cite the visible signal from the chunk.
