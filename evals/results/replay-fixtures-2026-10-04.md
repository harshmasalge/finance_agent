# Eval run replay-fixtures-2026-10-04

mode: replay · commit 89593be · 2026-10-04T10:51:41+00:00

| metric | value |
|---|---|
| n_evaluated | 6 |
| case_pass_rate | 33.3% |
| routing_accuracy | 100.0% |
| ticker_f1 | 100.0% |
| answer_type_accuracy | 100.0% |
| schema_validity | 100.0% |
| citation_coverage | 100.0% |
| citation_validity | 100.0% |
| number_grounding | 100.0% |
| claims_fully_grounded | 100.0% |
| grounding_false_positive_rate | 0.8% |
| forbidden_pass_rate | 100.0% |
| must_include_rate | 40.0% |
| verdict_determinism | 100.0% |
| verdict_consistency | 33.3% |
| rule_checker_pass_rate | 60.0% |
| llm_validator_pass_rate | 20.0% |
| latency_p50_s | 32.35 |
| latency_p95_s | 40.4 |
| total_tokens_mean | n/a |
| judge_faithfulness | n/a |

| case | status | passed | failed checks |
|---|---|---|---|
| research-techm | evaluated | False | must_include, verdict_consistency |
| research-policybazaar | evaluated | True | - |
| research-lt | not_run | n/a | no recorded answer for this question (live mode only) |
| research-sbi | not_run | n/a | no recorded answer for this question (live mode only) |
| research-bajaj-auto | not_run | n/a | no recorded answer for this question (live mode only) |
| research-tatasteel | not_run | n/a | no recorded answer for this question (live mode only) |
| research-zomato | not_run | n/a | no recorded answer for this question (live mode only) |
| followup-infy | not_run | n/a | no recorded answer for this question (live mode only) |
| followup-sentiment-hdfc | not_run | n/a | no recorded answer for this question (live mode only) |
| followup-compare-icici | not_run | n/a | no recorded answer for this question (live mode only) |
| compare-tcs-infy | evaluated | False | verdict_consistency |
| compare-mm-maruti | not_run | n/a | no recorded answer for this question (live mode only) |
| compare-three-fmcg | not_run | n/a | no recorded answer for this question (live mode only) |
| sentiment-reliance | not_run | n/a | no recorded answer for this question (live mode only) |
| sentiment-tcs | not_run | n/a | no recorded answer for this question (live mode only) |
| portfolio-health | evaluated | False | must_include, rule_checker |
| portfolio-risk | not_run | n/a | no recorded answer for this question (live mode only) |
| portfolio-pnl | not_run | n/a | no recorded answer for this question (live mode only) |
| ideas-add | evaluated | False | must_include, rule_checker |
| ideas-diversify | not_run | n/a | no recorded answer for this question (live mode only) |
| clarify-buy-it | not_run | n/a | no recorded answer for this question (live mode only) |
| clarify-good-stock | not_run | n/a | no recorded answer for this question (live mode only) |
| direct-hi | evaluated | True | - |
| direct-pe | not_run | n/a | no recorded answer for this question (live mode only) |
| out-of-scope-apple | not_run | n/a | no recorded answer for this question (live mode only) |
