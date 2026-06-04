# ITB Matching Evaluation Results

Scope:

- Sections: `6`, `7`
- Evaluation outputs compared:
  - `output/current_test_env/evaluation/matching/R_N_MDL`
  - `output/current_test_env/evaluation/matching/R_N_MDL_structured`
  - `output/current_test_env/evaluation/matching/all_projects`
  - `output/current_test_env/evaluation/matching/all_projects_structured`

## Overview

| Run | Ground Truth | Matching Dir | Positive Queries |
| --- | --- | --- | ---: |
| `R_N_MDL` | `R_N_MDL_ground_truth_final.csv` | `matching/R_N_MDL` | 19 |
| `R_N_MDL_structured` | `R_N_MDL_ground_truth_final.csv` | `matching_structured_R_N_MDL/R_N_MDL` | 19 |
| `all_projects` | `all_projects_ground_truth_final.csv` | `matching_all_projects` | 26 |
| `all_projects_structured` | `all_projects_ground_truth_final.csv` | `matching_structured_all_projects` | 26 |

## Cross-encoder Results

| Run | Mode | Recall@20 | HitRate@20 |
| --- | --- | ---: | ---: |
| `R_N_MDL` | `keyword` | 0.3935 | 0.4211 |
| `R_N_MDL` | `semantic` | 0.7267 | 0.7895 |
| `R_N_MDL` | `hybrid` | 0.7768 | 0.8421 |
| `R_N_MDL_structured` | `keyword` | 0.3910 | 0.4211 |
| `R_N_MDL_structured` | `semantic` | 0.7423 | 0.7895 |
| `R_N_MDL_structured` | `hybrid` | 0.7448 | 0.7895 |
| `all_projects` | `keyword` | 0.3122 | 0.4231 |
| `all_projects` | `semantic` | 0.7273 | 0.8462 |
| `all_projects` | `hybrid` | 0.8590 | 0.9615 |
| `all_projects_structured` | `keyword` | 0.1799 | 0.2692 |
| `all_projects_structured` | `semantic` | 0.3254 | 0.5000 |
| `all_projects_structured` | `hybrid` | 0.3677 | 0.5000 |

## Retrieval Results

| Run | Mode | Recall@100 |
| --- | --- | ---: |
| `R_N_MDL` | `keyword` | 0.3935 |
| `R_N_MDL` | `semantic` | 0.9424 |
| `R_N_MDL` | `hybrid` | 0.9900 |
| `R_N_MDL_structured` | `keyword` | 0.3935 |
| `R_N_MDL_structured` | `semantic` | 0.9424 |
| `R_N_MDL_structured` | `hybrid` | 0.9875 |
| `all_projects` | `keyword` | 0.3122 |
| `all_projects` | `semantic` | 0.8507 |
| `all_projects` | `hybrid` | 0.9588 |
| `all_projects_structured` | `keyword` | 0.3122 |
| `all_projects_structured` | `semantic` | 0.8507 |
| `all_projects_structured` | `hybrid` | 0.9588 |

## Quick Comparison

- Best cross-encoder result currently: `all_projects` + `hybrid`
  - `Recall@20 = 0.8590`
  - `HitRate@20 = 0.9615`
- Best retrieval result currently: `R_N_MDL` + `hybrid`
  - `Recall@100 = 0.9900`
- In `R_N_MDL` full_chunk, ranking quality is:
  - `hybrid` > `semantic` > `keyword`
- In `R_N_MDL_structured`, ranking quality is:
  - `hybrid` ~= `semantic` >> `keyword`
- `R_N_MDL_structured` is close to `R_N_MDL` on cross-encoder ranking:
  - `keyword`: `0.3935 -> 0.3910`
  - `semantic`: `0.7267 -> 0.7423`
  - `hybrid`: `0.7768 -> 0.7448`
- `all_projects_structured` is much weaker than `all_projects` on cross-encoder ranking:
  - `keyword`: `0.3122 -> 0.1799`
  - `semantic`: `0.7273 -> 0.3254`
  - `hybrid`: `0.8590 -> 0.3677`
- Retrieval recall for `R_N_MDL` and `R_N_MDL_structured` is nearly the same.
- Retrieval recall for `all_projects` and `all_projects_structured` is the same, so the gap comes from re-ranking, not retrieval.

## Final Conclusion

- Best overall run: `all_projects` + `hybrid` with `full_chunk`
  - This is the strongest final ranking result in the current benchmark.
  - `Recall@20 = 0.8590`
  - `HitRate@20 = 0.9615`
  - In practice, this means it returns the highest share of correct MDL documents in the final top 20, and for almost every positive query it surfaces at least one correct result.
- Best retrieval-only run: `R_N_MDL` + `hybrid` with `full_chunk`
  - `Recall@100 = 0.9900`
  - This is the strongest candidate generation result before reranking.
  - In practice, it almost always pulls the correct MDL into the top 100 pool.
- Best choice for `R_N_MDL` scope:
  - `full_chunk` is still the better default.
  - `structured` is close, but slightly weaker on `hybrid` final ranking:
    - `Recall@20`: `0.7768` vs `0.7448`
    - `HitRate@20`: `0.8421` vs `0.7895`
  - Conclusion: for project-scoped matching, `structured` is acceptable, but `full_chunk` is safer as the main benchmark setting.
- Best choice for `all_projects` scope:
  - `full_chunk` is clearly better than `structured`.
  - The biggest gap is in reranking quality, especially for `hybrid`:
    - `Recall@20`: `0.8590` vs `0.3677`
    - `HitRate@20`: `0.9615` vs `0.5000`
  - Conclusion: for all-project search, `structured` should not be used as the default benchmark mode in its current form.
- Final recommendation:
  - Use `hybrid + full_chunk` as the default benchmark configuration.
  - Use `R_N_MDL + hybrid + full_chunk` when you want the strongest project-specific retrieval.
  - Use `all_projects + hybrid + full_chunk` when you want the strongest end-to-end ranking across the full Neo4j MDL corpus.

## Source Files

- [R_N_MDL summary](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/R_N_MDL/summary.csv>)
- [R_N_MDL report](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/R_N_MDL/report.json>)
- [R_N_MDL_structured summary](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/R_N_MDL_structured/summary.csv>)
- [R_N_MDL_structured report](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/R_N_MDL_structured/report.json>)
- [all_projects summary](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/all_projects/summary.csv>)
- [all_projects report](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/all_projects/report.json>)
- [all_projects_structured summary](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/all_projects_structured/summary.csv>)
- [all_projects_structured report](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/all_projects_structured/report.json>)
