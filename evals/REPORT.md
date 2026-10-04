# Evaluation harness - report

Two questions, answered separately:
1. **Are the answers well-formed and grounded?** -> answer-quality metrics on real recorded answers (`evals/run.py`).
2. **Does the signal scorecard have predictive value?** -> point-in-time backtest (`evals/backtest.py`).

## What was built
| File | Purpose |
|---|---|
| `evals/dataset.yaml` | 25 cases: all intents (research, comparison, sentiment, portfolio, ideas, clarify, direct, out-of-scope), follow-ups, tricky names (policy bazaar -> POLICYBZR.NS, L&T -> LT.NS, SBI -> SBIN.NS, Zomato -> ETERNAL.NS, HUL) |
| `evals/metrics.py` | Pure metric functions (routing, ticker P/R/F1, schema validity, citation coverage/validity, tolerant number grounding + perturbation negative control, forbidden content, must_include, verdict determinism/consistency, rule checker, latency percentiles, tokens) |
| `evals/run.py` | `--mode replay` (fixtures, no LLM) and `--mode live` (in-process `/agent/chat`); `--judge` adds LLM faithfulness via injectable LLM (`evals/judge.py`) |
| `evals/backtest.py` | NIFTY 50 price-factor scorecard backtest, one batched yfinance download cached in `evals/cache/` (git-ignored) |
| `evals/router.py` | Read-only `/evals` API |
| `frontend/src/components/Evaluation.tsx` (+ `evaluation/types.ts`) | KPI tiles, per-case pass/fail drill-down, backtest table + single-axis bar chart, RAG card |
| `evals/results/` | `replay-fixtures-2026-10-04.{json,md}`, `backtest_latest.json` |

## How to run
```bash
python -m evals.run --mode replay --fixtures backend/tests/fixtures/answers.json
python -m evals.run --mode live [--cases research-lt] [--judge]   # needs LLM credit; not verified here
python -m evals.backtest [--refresh]                               # cached prices unless --refresh
python -m pytest evals/tests -q
```

## Replay results (6 recorded real answers; 19 cases need live mode)
Routing 100% · ticker F1 100% · answer type 100% · schema 100% · citation coverage 100% (51 claims) ·
citation validity 100% · number grounding 100% (perturbation control: 0.8% of +/-10% perturbed numbers
still "grounded", so the matcher is strict) · forbidden content 100% · verdict determinism 100% ·
must_include 40% · verdict consistency 33% · rule checker 60% · LLM validator passed 20% (informational) ·
latency p50 32.4 s / p95 40.4 s · **case pass rate 2/6**. Re-running replay reproduces identical numbers.

Failures are real: three answers miss a section the synthesis prompt requires ('Why this verdict',
'Suggested actions', 'Caveats'); two research/compare answers were recorded before the scorecard
existed and their LLM-chosen verdict disagrees with the recomputed scorecard.

## Backtest (12 monthly rebalances Sep 2025-Aug 2026, 30-trading-day excess return vs ^NSEI)
| Bucket | n | Hit rate | Mean excess | Median excess |
|---|---|---|---|---|
| BUY | 258 | 51.6% (>0) | +0.52 pp | +0.23 pp |
| HOLD | 101 | n/a (48.5% outperform) | +0.59 pp | -0.30 pp |
| SELL | 220 | 46.4% (<0) | +1.94 pp | +1.00 pp |
| All stocks | 579 | 51.8% outperform | +1.07 pp | +0.49 pp |

BUY-minus-SELL mean excess **-1.43 pp** (95% CI by resampling dates [-2.70, -0.02]); mean rank IC -0.07.
Per factor: RSI (mean-reversion) IC +0.11, positive on 10/12 dates; trend, momentum and 3-month return
negative. **Honest reading: the price-only scorecard showed no edge in this window; trend/momentum
signals were contrarian-wrong, RSI was the only useful factor.**

## Caveats
Price factors only (fundamentals, sentiment, Prophet, XGBoost excluded - no point-in-time data), so this
does not validate the full live verdict. Survivorship bias (today's NIFTY 50 applied to the past).
Overlapping windows; one market regime; no costs. Suspected unadjusted corporate actions excluded
(TMPV.NS demerger, TRENT.NS). Replay covers only 6 cases; token/cost and judge faithfulness are n/a
in replay (not recorded / no LLM).

## Known gaps
Live mode and the judge are implemented and tested with fakes only. Dataset expectations were written
by hand, not reviewed by a second person.
