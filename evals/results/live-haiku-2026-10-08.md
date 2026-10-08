# Eval run live-haiku-2026-10-08

mode: live · commit 4f87d70 · 2026-10-08T06:26:08+00:00

| metric | value |
|---|---|
| n_evaluated | 19 |
| case_pass_rate | 63.2% |
| routing_accuracy | 94.7% |
| ticker_f1 | 94.7% |
| answer_type_accuracy | 100.0% |
| schema_validity | 100.0% |
| citation_coverage | 99.6% |
| citation_validity | 100.0% |
| number_grounding | 90.6% |
| claims_fully_grounded | 81.8% |
| grounding_false_positive_rate | 5.7% |
| forbidden_pass_rate | 94.7% |
| must_include_rate | 100.0% |
| verdict_determinism | 100.0% |
| verdict_consistency | 100.0% |
| rule_checker_pass_rate | 93.3% |
| llm_validator_pass_rate | 46.7% |
| latency_p50_s | 31.5 |
| latency_p95_s | 84.97 |
| total_tokens_mean | n/a |
| judge_faithfulness | n/a |

| case | status | passed | failed checks |
|---|---|---|---|
| research-techm | not_run | n/a | not asked yet |
| research-policybazaar | not_run | n/a | not asked yet |
| research-lt | evaluated | False | number_grounding |
| research-sbi | evaluated | True | - |
| research-bajaj-auto | evaluated | True | - |
| research-tatasteel | evaluated | True | - |
| research-zomato | evaluated | False | tickers |
| followup-infy | evaluated | True | - |
| followup-sentiment-hdfc | evaluated | True | - |
| followup-compare-icici | evaluated | False | citation_coverage, number_grounding, rule_checker |
| compare-tcs-infy | not_run | n/a | not asked yet |
| compare-mm-maruti | evaluated | True | - |
| compare-three-fmcg | evaluated | True | - |
| sentiment-reliance | evaluated | True | - |
| sentiment-tcs | evaluated | True | - |
| portfolio-health | not_run | n/a | not asked yet |
| portfolio-risk | evaluated | False | number_grounding |
| portfolio-pnl | evaluated | False | number_grounding |
| ideas-add | not_run | n/a | not asked yet |
| ideas-diversify | evaluated | False | number_grounding |
| clarify-buy-it | evaluated | True | - |
| clarify-good-stock | evaluated | True | - |
| direct-hi | not_run | n/a | not asked yet |
| direct-pe | evaluated | True | - |
| out-of-scope-apple | evaluated | False | routing, forbidden_content |
