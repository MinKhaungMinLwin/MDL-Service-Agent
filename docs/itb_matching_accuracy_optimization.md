# ITB-MDL Accuracy Optimization Notes

This note summarizes the highest-value optimization directions for the current ITB -> matching -> ground truth -> evaluation flow.

## Current Read of the System

- Retrieval is already strong, especially in `hybrid` mode.
- The main quality gap is in final reranking, not initial candidate retrieval.
- `full_chunk` is currently the better default cross-encoder query mode.

Evidence from current evaluation results:

- `R_N_MDL + hybrid`: `Recall@100 = 0.9900`
- `all_projects + hybrid`: `Recall@100 = 0.9588`
- Best overall final ranking: `all_projects + hybrid + full_chunk`

This means the pipeline is usually finding the right MDL candidates, but the reranker still has room to rank them more accurately.

## Highest-Priority Optimizations

### 1. Improve cross-encoder candidate text

Status: DONE ✅

What was changed:

- The cross-encoder query is already fairly rich.
- The MDL candidate text used for reranking now includes full raw `text_content`.
- In [src/matching_service/ranking.py](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/src/matching_service/ranking.py:44>), the candidate text now includes:
  - `title`
  - `equipment`
  - `system`
  - `building`
  - `study_survey`
  - `others`
  - `deliverable`
  - `text_content`

Why this matters:

- The system is already good at retrieving correct documents.
- The reranker now has real MDL body text, not just shallow metadata.
- This should help the cross-encoder distinguish:
  - direct matches
  - partial matches
  - adjacent-but-wrong documents

What to do next:

- Rebuild and rerun:
  - matching
  - ground truth
  - evaluation
- Compare new benchmark results against the previous baseline.
- If full raw text adds too much noise, the next refinement should be:
  - trimmed `text_content`
  - or a more controlled excerpt strategy

### 2. Keep `full_chunk` as the default reranking mode

Status: DONE ✅

Current results show:

- `full_chunk` consistently performs better than `structured` overall.
- `structured` is acceptable for comparison, but not the accuracy-first default.
- The gap is especially large in `all_projects`.

Recommended direction:

- Use `full_chunk` as the main benchmark/default mode.
- Keep `structured` only as an ablation or comparison mode.
- No code change is required here as long as `full_chunk` remains the operational default.

### 3. Focus optimization on `hybrid`, not `keyword`

Current benchmark pattern:

- `keyword` is weakest
- `semantic` is much better
- `hybrid` is best

Current hybrid merge logic in [src/matching_service/retrieval.py](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/src/matching_service/retrieval.py:82>) is already a sensible baseline using RRF.

Recommended direction:

- Spend tuning effort on `hybrid`.
- Do not spend much time trying to make `keyword` mode the primary winner.
- Keep in mind that current `hybrid` retrieval is already strong, so the immediate bottleneck still appears to be reranking rather than RRF itself.

## Medium-Priority Optimizations

### 4. Increase reranking candidate pool when needed

Current flow:

- retrieve candidates
- cut to `retrieval_candidate_limit`
- rerank
- keep `output_limit`

Current benchmark read:

- `R_N_MDL + hybrid`: `Recall@100 = 0.9900`
- `all_projects + hybrid`: `Recall@100 = 0.9588`

This suggests retrieval is already strong, so this is **not a current priority**.
It should only be revisited if later experiments show the reranker is still missing positives because they sit just outside the rerank pool.

Recommended direction:

- keep this as a secondary experiment, not an immediate implementation
- benchmark a larger `retrieval_candidate_limit` only after reranking-side improvements are re-evaluated
- if tested, prioritize `all_projects`, where the corpus is noisier

### 5. Refine semantic query construction

Current semantic query generation in [src/matching_service/query.py](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/src/matching_service/query.py:74>) is simple:

- `depth_terms`
- `keyword_terms`
- abbreviation expansions

This is reasonable, but may still include noise, especially for all-project search.

Recommended direction:

- test cleaner semantic query variants
- bias more toward deeper or more specific depth terms
- reduce overly broad terms when they add noise
- review abbreviation expansion impact on retrieval quality

## Lower-Priority Optimizations

### 6. Tune `keyword` mode only if needed for diagnostics

`keyword` is useful as a baseline, but not the best path for accuracy improvements.

### 7. Treat `structured` as a benchmark variant, not a default

The current results do not support using `structured` as the main mode for best accuracy.

## Recommended Optimization Order

1. Rebuild and benchmark the new `text_content` reranking change
2. Optimize and benchmark on `hybrid + full_chunk`
3. Tune `retrieval_candidate_limit`
4. Tune hybrid retrieval behavior and semantic-query construction
5. If needed, refine from full raw `text_content` to a more controlled excerpt strategy

## Practical Conclusion

If only one optimization should be done first:

**Improve the cross-encoder candidate text by incorporating MDL `text_content`.** DONE ✅

The next step is to rerun the benchmark and verify whether full raw `text_content` improves final ranking accuracy in practice.

## Non-Fine-Tuning Experiment Backlog

The following experiments do not require model fine-tuning and are good candidates for step-by-step benchmarking.

### A. Tune `retrieval_candidate_limit`

Priority: LOW for the current benchmark state

Why:

- The cross-encoder can only rerank what first-stage retrieval passes to it.
- If the correct MDL is found but falls just outside the rerank pool, final ranking cannot recover it.

Current read from this repo:

- `Recall@100` is already high in the strongest runs
- the bigger observed gap is between retrieval quality and final reranking quality
- this means reranking is the more likely bottleneck right now

What to try:

- do this only after reranking-side experiments are re-benchmarked
- benchmark larger `retrieval_candidate_limit` values on `hybrid + full_chunk`
- prioritize `all_projects`, where retrieval noise is higher

References:

- Sentence Transformers Retrieve & Re-Rank:
  - https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- Cross-Encoder usage:
  - https://sbert.net/docs/cross_encoder/usage/usage.html

### B. Tune hybrid fusion / RRF

Priority: LOW for the current benchmark state

Why:

- `hybrid` is already the strongest retrieval mode in the current benchmark.
- Current `Recall@100` is already high in the strongest runs, so there is no strong evidence yet that RRF is the main bottleneck.
- This remains a valid experiment, but it should come after reranking-side improvements are re-benchmarked.

What to try:

- benchmark different `rrf_k` values only after reranking-side changes are re-evaluated
- compare different keyword/semantic candidate balance assumptions
- inspect tie-break behavior between BM25 and semantic scores

References:

- Reciprocal Rank Fusion paper:
  - https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf

### C. Refine semantic query construction

Priority: LOW for the current benchmark state

Why:

- Current semantic query building is simple and may include broad or noisy terms.
- Better semantic queries can improve recall without changing the retriever model itself.

What to try:

- bias more toward deeper / more specific depth terms
- reduce broad terms when they do not help
- review abbreviation expansion impact on retrieval quality
- benchmark multiple semantic query templates

References:

- HyDE:
  - https://arxiv.org/abs/2212.10496
- Generative Relevance Feedback:
  - https://arxiv.org/pdf/2304.13157

### D. Benchmark different cross-encoder candidate formatting

Why:

- Full raw `text_content` may help, but it may also add noise.
- Candidate formatting can materially change reranking quality even without any model retraining.

What to try:

- full raw `text_content`
- trimmed `text_content`
- front excerpt only
- metadata + selected snippet
- metadata + keyword-overlap snippet

References:

- Sentence Transformers Retrieve & Re-Rank:
  - https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- Cross-Encoder usage:
  - https://sbert.net/docs/cross_encoder/usage/usage.html

### E. Try query expansion / HyDE-style retrieval

Why:

- ITB wording and MDL wording can differ even when they refer to the same concept.
- Query expansion can help the semantic branch retrieve conceptually matching documents.

What to try:

- generate expanded semantic queries
- generate pseudo-MDL style text before embedding
- compare plain semantic query vs expanded query vs HyDE-style pseudo document

References:

- HyDE:
  - https://arxiv.org/abs/2212.10496
- Query2doc:
  - https://arxiv.org/abs/2303.07678
- Doc2Query--:
  - https://arxiv.org/abs/2301.03266

### F. Benchmark stronger pretrained rerankers

Why:

- Accuracy can improve by switching to a stronger pretrained reranker even without fine-tuning.
- This is often cheaper than training and easier to benchmark quickly.

What to try:

- compare multiple pretrained cross-encoders
- compare stronger reranker families such as BGE or Jina rerankers if infra allows

References:

- Sentence Transformers pretrained cross-encoders:
  - https://www.sbert.net/docs/pretrained_models.html#cross-encoders
- BGE reranker:
  - https://huggingface.co/BAAI/bge-reranker-base
- Jina reranker:
  - https://huggingface.co/jinaai/jina-reranker-v1-tiny-en

### G. Evaluate stronger retrieval architectures if needed

Why:

- If the current retrieval stack plateaus, architecture changes may be the next step.
- These are bigger experiments, but worth keeping on the roadmap.

What to try:

- sparse learned retrieval such as SPLADE for the lexical branch
- late-interaction retrieval such as ColBERTv2 for the semantic branch

References:

- SPLADE v2:
  - https://arxiv.org/abs/2109.10086
- Sentence Transformers sparse retrieval docs:
  - https://sbert.net/examples/sparse_encoder/applications/semantic_search/README.html
- ColBERTv2:
  - https://arxiv.org/abs/2112.01488

## Suggested Non-Fine-Tuning Order

1. Benchmark cross-encoder candidate formatting
2. Refine semantic query construction
3. Try query expansion / HyDE
4. Benchmark stronger pretrained rerankers
5. Tune `hybrid` / RRF only if reranking-side changes are still not enough
6. Benchmark `retrieval_candidate_limit` only if reranking-side changes are still not enough
7. Consider SPLADE / ColBERTv2 only if simpler experiments plateau
