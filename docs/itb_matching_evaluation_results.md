# ITB Matching Evaluation Results

Scope:

- Sections: `6`, `7`
- Evaluation outputs compared:
  - `output/current_test_env/evaluation/matching/R_N_MDL`
  - `output/current_test_env/evaluation/matching/R_N_MDL_structured`
  - `output/current_test_env/evaluation/matching/all_projects`
  - `output/current_test_env/evaluation/matching/all_projects_structured`

## Overview

| Run | Ground Truth | Matching Dir | Positive Queries | Coverage |
| --- | --- | --- | ---: | ---: |
| `R_N_MDL` | `R_N_MDL_ground_truth_final.csv` | `matching/R_N_MDL` | 19 | 0.1681 |
| `R_N_MDL_structured` | `R_N_MDL_ground_truth_final.csv` | `matching_structured_R_N_MDL/R_N_MDL` | 19 | 0.1681 |
| `all_projects` | `all_projects_ground_truth_final.csv` | `matching_all_projects` | 26 | 0.2301 |
| `all_projects_structured` | `all_projects_ground_truth_final.csv` | `matching_structured_all_projects` | 26 | 0.2301 |

## Cross-encoder Results

| Run | Mode | Recall@20 | HitRate@20 | Judged@20 |
| --- | --- | ---: | ---: | ---: |
| `R_N_MDL` | `keyword` | 0.3935 | 0.4211 | 0.0369 |
| `R_N_MDL` | `semantic` | 0.7267 | 0.7895 | 0.0257 |
| `R_N_MDL` | `hybrid` | 0.7768 | 0.8421 | 0.0257 |
| `R_N_MDL_structured` | `keyword` | 0.3910 | 0.4211 | 0.0364 |
| `R_N_MDL_structured` | `semantic` | 0.7423 | 0.7895 | 0.0248 |
| `R_N_MDL_structured` | `hybrid` | 0.7448 | 0.7895 | 0.0252 |
| `all_projects` | `keyword` | 0.3122 | 0.4231 | 0.0280 |
| `all_projects` | `semantic` | 0.7273 | 0.8462 | 0.0323 |
| `all_projects` | `hybrid` | 0.8590 | 0.9615 | 0.0367 |
| `all_projects_structured` | `keyword` | 0.1799 | 0.2692 | 0.0166 |
| `all_projects_structured` | `semantic` | 0.3254 | 0.5000 | 0.0150 |
| `all_projects_structured` | `hybrid` | 0.3677 | 0.5000 | 0.0142 |

## Retrieval Results

| Run | Mode | Recall@100 | Judged@100 |
| --- | --- | ---: | ---: |
| `R_N_MDL` | `keyword` | 0.3935 | 0.0321 |
| `R_N_MDL` | `semantic` | 0.9424 | 0.0073 |
| `R_N_MDL` | `hybrid` | 0.9900 | 0.0073 |
| `R_N_MDL_structured` | `keyword` | 0.3935 | 0.0321 |
| `R_N_MDL_structured` | `semantic` | 0.9424 | 0.0073 |
| `R_N_MDL_structured` | `hybrid` | 0.9875 | 0.0073 |
| `all_projects` | `keyword` | 0.3122 | 0.0164 |
| `all_projects` | `semantic` | 0.8507 | 0.0083 |
| `all_projects` | `hybrid` | 0.9588 | 0.0087 |
| `all_projects_structured` | `keyword` | 0.3122 | 0.0164 |
| `all_projects_structured` | `semantic` | 0.8507 | 0.0083 |
| `all_projects_structured` | `hybrid` | 0.9588 | 0.0087 |

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

## Source Files

- [R_N_MDL summary](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/R_N_MDL/summary.csv>)
- [R_N_MDL report](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/R_N_MDL/report.json>)
- [R_N_MDL_structured summary](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/R_N_MDL_structured/summary.csv>)
- [R_N_MDL_structured report](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/R_N_MDL_structured/report.json>)
- [all_projects summary](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/all_projects/summary.csv>)
- [all_projects report](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/all_projects/report.json>)
- [all_projects_structured summary](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/all_projects_structured/summary.csv>)
- [all_projects_structured report](</C:/Users/nguye/OneDrive/Máy tính/doosan-mdl/output/current_test_env/evaluation/matching/all_projects_structured/report.json>)
