# ITB Matching Reranking Research

Scope:

- Read current repo flow from ITB extract -> matching -> ground truth -> evaluation
- Focus on the current bottleneck: cross-encoder reranking quality is lower than retrieval top 100 quality
- Collect external approaches that fit this exact pipeline

## Current Flow In This Repo

Current matching pipeline:

```text
keyword retrieval
+ semantic retrieval
-> hybrid merge with RRF
-> top 100 retrieval pool
-> cross-encoder reranking
-> top 20 final output
```

Relevant code:

- Hybrid retrieval and RRF merge: [src/matching_service/retrieval.py](/C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/src/matching_service/retrieval.py)
- Cross-encoder reranking: [src/matching_service/ranking.py](/C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/src/matching_service/ranking.py)
- Query construction: [src/matching_service/query.py](/C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/src/matching_service/query.py)
- Matching service orchestration: [src/matching_service/service.py](/C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/src/matching_service/service.py)
- Evaluation metrics: [src/evaluation_service/matching_evaluation/metrics.py](/C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/src/evaluation_service/matching_evaluation/metrics.py)

## What The Current Benchmark Says

From [docs/itb_matching_evaluation_results.md](/C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/docs/itb_matching_evaluation_results.md):

- `R_N_MDL + hybrid`
  - `Recall@100 = 0.9900`
  - `Recall@20 = 0.7768`
- `all_projects + hybrid`
  - `Recall@100 = 0.9588`
  - `Recall@20 = 0.8590`
- `all_projects_structured + hybrid`
  - `Recall@100 = 0.9588`
  - `Recall@20 = 0.3677`

Conclusion:

```text
retrieval top 100 is already strong
the main bottleneck is reranking quality after top 100
```

This means:

- `retrieval_candidate_limit` is not the first thing to optimize
- `RRF` is not the main suspect right now
- reranking design is the highest-leverage place to improve

## Why The Current Reranker May Be Underperforming

Current reranker behavior:

- model default: `cross-encoder/ms-marco-MiniLM-L6-v2`
- reranks each candidate independently
- candidate text is a single blob:
  - `title`
  - `equipment`
  - `system`
  - `building`
  - `study_survey`
  - `others`
  - `deliverable`
  - `text_content`

Likely mismatch:

```text
retrieval works at document level
reranker is a small passage-ranking cross-encoder
candidate input is a long document-style blob
long input may be noisy and may also be truncated
```

So even when the correct MDL document is already in the top 100 pool, the reranker may not score it correctly enough to push it into the final top 20.

## Best-Fit External Approaches

### 1. Chunk-aware / passage-aware reranking

Idea:

- split each MDL candidate `text_content` into smaller chunks/passages
- score `(ITB query, MDL chunk)` pairs instead of one whole-document blob
- aggregate chunk scores per MDL doc, for example with `max`

Why it fits this repo:

- the current model family is designed for passage ranking
- this directly addresses the document-vs-passage mismatch
- it keeps the rest of the pipeline mostly intact

Why this is likely the best next approach:

```text
it targets the current reranking bottleneck directly
without first changing retrieval
```

### 2. Benchmark a stronger pretrained reranker

Idea:

- keep the same retrieve -> rerank architecture
- replace the current cross-encoder with a stronger pretrained reranker

Good benchmark candidates:

- `cross-encoder/ms-marco-MiniLM-L12-v2`
- `BAAI/bge-reranker-v2-m3`
- other stronger pretrained rerankers if infra allows

Why it fits this repo:

- very small code change
- easy to benchmark
- useful as a strong baseline before larger design changes

### 3. Listwise / setwise reranking

Idea:

- instead of scoring each candidate independently
- let the reranker compare multiple candidates for the same ITB query together

Why it may help:

- current top 100 pool is already good
- the problem is mostly final ordering inside that pool
- listwise or setwise methods are designed for exactly that

Tradeoff:

- more complex to implement
- slower
- harder to operationalize than a simple cross-encoder swap

### 4. Late-interaction retrieval / reranking such as ColBERTv2

Idea:

- use token-level interaction instead of one dense representation or one whole candidate blob

Why it may help:

- ITB-to-MDL matching often depends on small, specific technical phrases
- late interaction can capture these better than coarse whole-document scoring

Tradeoff:

- biggest architectural change
- highest effort

## Recommended Priority For This Repo

### Priority 1

Chunk-aware / passage-aware reranking

### Priority 2

Stronger pretrained reranker benchmark

### Priority 3

Listwise / setwise reranking

### Priority 4

ColBERTv2 or similar late-interaction architecture

## Practical Recommendation

If the goal is to improve accuracy with the current repo as efficiently as possible:

```text
1. keep hybrid + full_chunk as the retrieval baseline
2. improve reranking before touching retrieval
3. first try passage-aware reranking or a stronger pretrained reranker
4. only revisit retrieval-side tuning later if needed
```

## Sources

- Sentence Transformers CrossEncoder docs:
  - https://sbert.net/docs/package_reference/cross_encoder/model.html
- Sentence Transformers pretrained cross-encoders:
  - https://sbert.net/docs/cross_encoder/pretrained_models.html
- Sentence Transformers retrieve & rerank:
  - https://www.sbert.net/examples/applications/retrieve_rerank/README.html
- `cross-encoder/ms-marco-MiniLM-L6-v2` model card:
  - https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2
- Cohere rerank best practices:
  - https://docs.cohere.com/docs/reranking-best-practices
- BGE reranker v2 m3 model card:
  - https://huggingface.co/BAAI/bge-reranker-v2-m3
- Jina reranker docs:
  - https://jina.ai/en-US/reranker/
- Setwise ranking paper:
  - https://arxiv.org/abs/2310.09497
- Pairwise ranking prompting paper:
  - https://arxiv.org/abs/2306.17563
- ColBERTv2 paper:
  - https://arxiv.org/abs/2112.01488
