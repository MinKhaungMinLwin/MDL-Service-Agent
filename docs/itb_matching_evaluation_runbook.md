# ITB Matching Evaluation Runbook

Scope: run after ITB extract, only sections 6 and 7.

Keep:

```text
output/current_test_env/itb_extract/output_itb_section6_focused.csv
output/current_test_env/itb_extract/output_itb_section7_focused.csv
```

Flow:

```text
matching -> build ground truth -> audit ground truth -> evaluate
```

## Matching

Default matching uses `full_chunk`:

```text
Chunk Text + Depth + Keywords + Expanded terms
```

`structured` is the old/baseline cross-encoder query:

```text
Depth + Keywords + Expanded terms
```

Run matching in separate terminals.

Structured all-projects:

```powershell
uv run itb-match --retrieval-mode keyword --cross-encoder-query-mode structured --output-dir output/current_test_env/matching_structured
uv run itb-match --retrieval-mode semantic --cross-encoder-query-mode structured --output-dir output/current_test_env/matching_structured
uv run itb-match --retrieval-mode hybrid --cross-encoder-query-mode structured --output-dir output/current_test_env/matching_structured
```

Full-chunk all-projects:

```powershell
uv run itb-match --retrieval-mode keyword
uv run itb-match --retrieval-mode semantic
uv run itb-match --retrieval-mode hybrid
```

Structured R_N_MDL:

```powershell
uv run itb-match --retrieval-mode keyword --cross-encoder-query-mode structured --source-file "R&N_MDL.xlsx" --output-dir output/current_test_env/matching_structured
uv run itb-match --retrieval-mode semantic --cross-encoder-query-mode structured --source-file "R&N_MDL.xlsx" --output-dir output/current_test_env/matching_structured
uv run itb-match --retrieval-mode hybrid --cross-encoder-query-mode structured --source-file "R&N_MDL.xlsx" --output-dir output/current_test_env/matching_structured
```

Full-chunk R_N_MDL:

```powershell
uv run itb-match --retrieval-mode keyword --source-file "R&N_MDL.xlsx"
uv run itb-match --retrieval-mode semantic --source-file "R&N_MDL.xlsx"
uv run itb-match --retrieval-mode hybrid --source-file "R&N_MDL.xlsx"
```

## Ground Truth

Build:

```powershell
uv run itb-eval-build-ground-truth --sections 6 7 --resume
```

Audit:

```powershell
uv run itb-eval-audit-ground-truth --sections 6 7
```

Use this file for evaluation:

```text
output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth_final.csv
```

Suspicious rows are here for manual review:

```text
output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth_suspicious.csv
```

## Evaluate

Full-chunk all-projects:

```powershell
uv run itb-eval-matching `
  --ground-truth output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth_final.csv `
  --matching-dir output/current_test_env/matching `
  --output-dir output/current_test_env/evaluation/matching/full_chunk_all_projects `
  --sections 6 7
```

Structured all-projects:

```powershell
uv run itb-eval-matching `
  --ground-truth output/current_test_env/evaluation/ground_truth/itb_mdl_matching_ground_truth_final.csv `
  --matching-dir output/current_test_env/matching_structured `
  --output-dir output/current_test_env/evaluation/matching/structured_all_projects `
  --sections 6 7
```

Compare:

```text
output/current_test_env/evaluation/matching/full_chunk_all_projects/summary.csv
output/current_test_env/evaluation/matching/structured_all_projects/summary.csv
```

Key metrics:

```text
recall_at_100  = retrieval top 100 found true MDL docs
recall_at_20   = reranked top 20 found true MDL docs
hit_rate_at_20 = at least one true MDL doc appears in top 20
```
