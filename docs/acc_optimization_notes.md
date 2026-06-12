# ACC ITB-MDL Optimization Notes

This note summarizes possible optimization directions for the ACC experiment flow:

```text
ITB ACC chunks -> matching candidates -> LLM final selector -> project-level MDL list
```

The goal is to improve both:

- Accuracy: correct MDL documents are found and selected.
- Performance: experiments run faster and are easier to compare.

## Current Flow

1. ACC ITB chunks are used as input.
2. Matching retrieves MDL candidates from Neo4j using hybrid search.
3. RRF keeps the final Top-K candidate list.
4. The LLM final selector chooses `doc_id` values from the candidate list.
5. Project-level merge deduplicates selected MDLs into the final `1 ITB -> n MDLs` output.
6. Evaluation compares output against ACC ground truth.

## Main Observation

The final quality depends mostly on the candidate list before the LLM step.

If the correct MDL document is not in the Top-K candidates, the LLM cannot recover it. If the Top-K list is noisy, the LLM selector becomes unstable and may select extra unrelated documents.

So the best optimization direction is:

```text
Improve retrieval and ranking first, then use the LLM only as the final business decision layer.
```

## Accuracy Optimization

### 1. Improve MDL Search Text

The MDL data in Neo4j should contain a stronger searchable representation.

Instead of relying only on separate fields like title, equipment, system, deliverable, and text content, add a combined field such as `search_text` or `retrieval_text`.

Suggested content:

- document number
- title
- equipment
- system
- building
- study/survey
- others
- deliverable
- text content
- normalized abbreviations
- short business description if available

Why this helps:

- BM25/full-text search gets richer text.
- Vector search gets better semantic meaning.
- RRF receives better rankings from both search channels.

### 2. Use Multiple Query Views

One ITB chunk can contain different useful signals. Instead of using only one query representation, create multiple query views and merge them with RRF.

Useful query views:

- Full chunk text
- Depth context
- Keywords
- Extracted equipment/system/deliverable/action intent
- Abbreviation-expanded terms

Why this helps:

- Depth terms catch hierarchy meaning.
- Keywords catch explicit extracted terms.
- Full chunk catches business requirement context.
- Intent terms catch document-registration meaning.

### 3. Add Business-Aware Ranking Signals

RRF is useful, but it treats ranking sources quite neutrally. The business problem has stronger signals that can be used for boost or tie-break.

Possible generic boosts:

- Same project match
- Equipment match
- System match
- Deliverable match
- Document title matches required deliverable
- Candidate appears in both keyword and semantic results
- Candidate appears across multiple query views

This should stay business-level and not hard-code ACC-specific rules.

### 4. Try a Stronger Reranker

The current RRF-only flow is fast, but a stronger reranker may improve the final Top-K candidate quality.

Options:

- Use cross-encoder mode for comparison.
- Try a stronger multilingual/domain reranker.
- Fine-tune a reranker later if enough verified ground truth exists.

This is especially useful when retrieval finds the correct docs, but RRF does not keep them high enough.

### 5. Make LLM Selector See the Whole Top-K

If `rrf_k = 60` but `candidate_batch_size = 20`, the LLM sees candidates in three separate batches. It cannot compare all 60 candidates globally.

For better accuracy:

```text
candidate_batch_size should usually match rrf_k
```

Example:

```text
rrf_k = 60
candidate_batch_size = 60
```

If batching is needed for token limits, add a second consolidation step after batch selection.

### 6. Use Stricter Structured Output

The LLM selector should only return candidate `doc_id` values.

Current JSON output is acceptable, but stricter structured output can reduce instability:

- `chunk_id` must match input chunk id.
- `selected_doc_ids` must be an array.
- selected ids must come from the supplied candidate list.

If supported by the model/runtime, JSON Schema with enum candidate ids is better than loose JSON mode.

## Performance Optimization

### 1. Cache Embeddings

Semantic query embeddings should be cached by normalized query text.

Why this helps:

- Repeated experiment runs do not call embedding API again for the same query.
- Comparing top 200, 300, and 500 becomes faster.

### 2. Cache Matching Results by Experiment Config

Matching output can be cached using:

- input file hash
- retrieval candidate count
- RRF output limit
- rerank mode
- source project mode
- abbreviation/rules version

Why this helps:

- Running evaluation or LLM selector again does not require rerunning matching.
- Different experiments are easier to compare.

### 3. Avoid Re-querying for Smaller Top-K

If a run already has retrieval top 500, then top 300 or top 200 can be derived from the same retrieval artifact.

Suggested approach:

```text
Run largest retrieval pool once.
Create smaller Top-K experiments from the saved retrieval candidates.
```

### 4. Optimize Same-Project Search

Same-project search currently filters by `source_file`. If the search limit is high, Neo4j may need to scan more candidates before filtering.

Possible optimization:

- Add project/source-file-specific index or query path.
- Store project-specific candidate pools.
- Pre-filter candidates by source file before ranking when possible.

## Evaluation Notes

For ACC-only experiment:

- Recall is the most important metric.
- Precision is useful but should be interpreted carefully, because ground truth only covers ACC documents.
- Some predicted non-ACC documents may be valid for other scopes but look like false positives under ACC-only ground truth.

Recommended evaluation focus:

- Retrieval recall at candidate pool size, for example `recall@300`.
- Final candidate recall, for example `rrf@60`.
- LLM selector recall on positive ACC chunks.
- Project-level recall after merge.

## Suggested Priority

1. Improve MDL `search_text` / `retrieval_text`.
2. Add multi-query RRF using depth, keyword, full chunk, and intent views.
3. Compare RRF-only with stronger reranker.
4. Make LLM selector see the full Top-K candidate list.
5. Add embedding and matching-result cache.
6. Use stricter structured output for LLM selector.

## Practical Summary

The LLM selector should not be responsible for fixing poor retrieval.

The best target state is:

```text
Top-K candidates are already mostly correct and complete.
LLM selector only makes the final business-level registration decision.
Project-level merge only deduplicates and formats the final output.
```

