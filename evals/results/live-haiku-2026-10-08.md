# Eval run live-haiku-2026-10-08

mode: live · commit 271aeb3 · 2026-10-08T06:08:59+00:00

| metric | value |
|---|---|
| n_evaluated | 3 |
| case_pass_rate | 66.7% |
| routing_accuracy | 100.0% |
| ticker_f1 | 100.0% |
| answer_type_accuracy | 100.0% |
| schema_validity | 100.0% |
| citation_coverage | 100.0% |
| citation_validity | 100.0% |
| number_grounding | 94.2% |
| claims_fully_grounded | 90.0% |
| grounding_false_positive_rate | 5.8% |
| forbidden_pass_rate | 100.0% |
| must_include_rate | 100.0% |
| verdict_determinism | 100.0% |
| verdict_consistency | 100.0% |
| rule_checker_pass_rate | 100.0% |
| llm_validator_pass_rate | 33.3% |
| latency_p50_s | 76.1 |
| latency_p95_s | 146.21 |
| total_tokens_mean | n/a |
| judge_faithfulness | n/a |

| case | status | passed | failed checks |
|---|---|---|---|
| research-lt | evaluated | False | number_grounding |
| research-sbi | evaluated | True | - |
| research-bajaj-auto | evaluated | True | - |
