# ITB Matching Evaluation Runbook

Scope: run after ITB extract, only sections 6 and 7, benchmark on `R_N_MDL`.

Keep:

```text
output/current_test_env/itb_extract/output_itb_section6_focused.csv
output/current_test_env/itb_extract/output_itb_section7_focused.csv
```

Flow:

```text
matching (R_N_MDL) -> build ground truth -> evaluate
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

R_N_MDL outputs:

```text
output/current_test_env/matching/R_N_MDL/keyword/
output/current_test_env/matching/R_N_MDL/semantic/
output/current_test_env/matching/R_N_MDL/hybrid/
```

## Ground Truth

Build:

```powershell
uv run itb-eval-build-ground-truth `
  --sections 6 7 `
  --matching-dir output/current_test_env/matching/R_N_MDL `
  --final-ground-truth output/current_test_env/evaluation/ground_truth/R_N_MDL_ground_truth_final.csv `
  --max-concurrency 5
```

Use this file for evaluation:

```text
output/current_test_env/evaluation/ground_truth/R_N_MDL_ground_truth_final.csv
```

## Evaluate

Full-chunk R_N_MDL:

```powershell
uv run itb-eval-matching `
  --ground-truth output/current_test_env/evaluation/ground_truth/R_N_MDL_ground_truth_final.csv `
  --matching-dir output/current_test_env/matching/R_N_MDL `
  --output-dir output/current_test_env/evaluation/matching/R_N_MDL `
  --sections 6 7
```

Structured R_N_MDL:

```powershell
uv run itb-eval-matching `
  --ground-truth output/current_test_env/evaluation/ground_truth/R_N_MDL_ground_truth_final.csv `
  --matching-dir output/current_test_env/matching_structured `
  --output-dir output/current_test_env/evaluation/matching/R_N_MDL_structured `
  --sections 6 7
```

Compare:

```text
output/current_test_env/evaluation/matching/R_N_MDL/summary.csv
output/current_test_env/evaluation/matching/R_N_MDL_structured/summary.csv
```

Key metrics:

```text
recall_at_100  = retrieval top 100 found true MDL docs
recall_at_20   = reranked top 20 found true MDL docs
hit_rate_at_20 = at least one true MDL doc appears in top 20
```
