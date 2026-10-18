# Decision record: EOD ML forecasting subsystem (intern proposal v1.0)

**Date:** 18 Oct 2026  **Branch:** `ml-forecasting-subsystem`  **Status:** proposed, awaiting sign-off before any implementation

**Inputs:** `eod_ml_forecasting_subsystem_requirements.md` (intern, 18 Oct); `docs/xgboost_review.md` and `docs/ml_signal_plan.md` (17 Oct); current code (`backend/agent/tools/ml_pipeline.py`, `backend/agent/scoring.py`); a NIFTY 500 data-coverage audit run today (section 5).

## 1. Verdict

**Accept with modifications.** The proposal is sound in method: pooled models, purged walk-forward, an immutable forecast ledger, EOD batch inference, explicit failure states. It also fixes the structural flaws of the current ML layer. It also fits our evidence better than the 17 Oct plan did. Our studies found return direction close to unpredictable (best IC 0.037, nothing significant after costs), but volatility clearly forecastable (XGBoost 8% lower error than the best naive forecast, calibrated 80% band). The proposal frames the job as a **probabilistic** forecast (quantiles and downside probabilities), and most of what a quantile forecast carries is the forecastable part, the width.

The modifications fall into four groups:

1. **Stronger baselines and calibration.** Add a distribution baseline that the models must beat, plus conformal calibration.
2. **Narrower v1.** Leave out point-in-time fundamentals, macro data and the full four-layer data platform. Use one gradient-boosting library and two horizons.
3. **No influence on the verdict.** Forecasts inform the risk view and get no BUY/SELL vote until the expected-return part passes the after-costs test from the 17 Oct plan.
4. **Honest evaluation periods.** 2023–2026 is no longer an untouched holdout, so the final test is forward shadow running.

The minimum validated first release is still useful **even if the ML models lose to the baseline**. A calibrated, vol-scaled forecast range stored in a ledger and scored over time is better than anything the app has today.

## 2. Current architecture vs proposal

| Aspect | Current (finsight-v2) | Intern proposal | Assessment |
|---|---|---|---|
| What is forecast | XGBoost: P(±2% move in 5d) as BUY/SELL/HOLD; Prophet: trend direction | Return distribution (quantiles, mean, event probabilities), absolute and excess, h = 1/5/10/20 | Proposal is better; matches what is forecastable |
| Training | Per request, one stock, 2y, ~380 rows; fitted fresh each call (~1 s) | Offline, pooled panel, scheduled retraining, versioned artifacts | Proposal is better; the current setup memorises (train acc 0.97, holdout 0.42) |
| Validation | One 80/20 split, no embargo, wrong baseline (0.33 vs 0.51 majority class) | Walk-forward, purge + embargo, untouched final holdout | Proposal is better; holdout claim needs amending (see M7) |
| Use in the app | A weighted vote in the deterministic scorecard (×credibility) | Read-only data for agents; human-reviewed decision support | Proposal is better; the current vote is below baseline |
| Record of forecasts | None; forecasts vanish after the chat | Immutable ledger, outcome resolution, monitoring | Proposal; this is the biggest operational gain |
| Failure behaviour | `available: false` from exceptions | Explicit stale/invalid/unavailable states, no silent fallback | Proposal |
| Data | yfinance on demand, NaN trailing row read, SMA-RSI | Data contracts, validation, raw/normalised layers | Proposal, but sized down for v1 |
| Infra | Postgres/Timescale, Redis, Celery beat already running | Python, Parquet, Postgres or SQLite, a scheduler | Compatible; reuse what exists |

**Proposal pros.** It answers a question the data can support. Its leakage controls are correct. It separates absolute and excess returns properly and warns against mixing their quantiles. Every forecast becomes auditable after the fact. It is explicit about what is unproven (section 13). It keeps scope to human-reviewed decision support.

**Proposal cons.**
- Its baselines are point baselines only ("predict zero" and "historical mean"), so they say nothing about the forecast range.
- It has no calibration step.
- It wants two boosting libraries.
- Its v1 depends on data that has no free source: point-in-time fundamentals and historical index membership.
- It treats the final holdout as clean when it is not.
- It defers every numeric acceptance threshold until after the experiments, which invites choosing them after seeing the results.
- It says nothing about what happens to the current XGBoost vote and the Prophet factor.

## 3. Component decisions

Each component is tagged **C** (confirmed requirement), **P** (implementation proposal), **E** (empirical question) or **X** (external dependency), as the intern asked.

| # | Component (proposal §) | Decision | Notes / modification |
|---|---|---|---|
| 1 | Probabilistic absolute-return target (2.1) | **Approve** (C) | Absolute returns are the right target for the risk view: what a holder experiences. |
| 2 | Excess return vs NIFTY 50 (2.2) | **Approve** (C) | Its role is the opportunity view (ranking). It stays out of the verdict until it passes the after-costs test (M6). |
| 3 | Horizons 1/5/10/20 (1.1) | **Amend** (P) | **5 and 20** in v1; 10 later through config. One-day forecasts are mostly noise, double the training cost, and our app is weekly-paced. |
| 4 | Outputs: mean, q10–q90, P(>0), threshold probabilities (2.3) | **Amend** (P) | Add **q05/q95** so the downside-threshold probabilities have tail support. Event probabilities come from the calibrated quantile function by interpolation; any threshold outside q05–q95 is reported as "beyond model range" rather than extrapolated. Brier score against the baseline decides whether this is good enough (E). |
| 5 | NIFTY 500 universe, point-in-time membership (3.5) | **Amend** (X) | v1 uses **today's NIFTY 500 list** (available from NSE; audit in §5) and states the survivorship bias. Point-in-time membership from NSE index-change notices is a separate later task. Yahoo has no delisted stocks either way. |
| 6 | 10 years of history (1.1) | **Approve** (X, verified) | 328/501 stocks have ≥10 years and 404 have ≥5. The model is pooled, so shorter histories still contribute. |
| 7 | Data sources: yfinance for research (3.1) | **Approve** (X) | Production rights remain an open item; outputs stay research/educational. |
| 8 | Corporate-action methodology (2.1, 3.3) | **Amend** (P/X) | Use Yahoo split-adjusted closes and dividend-adjusted closes for total return. Flag daily moves over 25% (80 such days across 48 stocks) and exclude any target window that spans one, pending validation against NSE corporate-action files. |
| 9 | Point-in-time fundamentals (3.4, 4.1E) | **Amend: earnings only in v1** (X) | *Revised 18 Oct after checking the data.* Yahoo's earnings history gives announcement dates with reported EPS and the consensus estimate back to 2005–2014. That is point-in-time by construction, and it covered 92% of a random 80-stock NIFTY 500 sample (79% with ≥ 3 years of quarters, 60% with ≥ 7.5 years). Full statements (ROE, ROCE, leverage, book value, cash flow) are only 4–5 periods deep on Yahoo, so those stay deferred until we have a filings-based source. For any statement data used later, the SEBI LODR results deadline (45 days after quarter end, 60 for the audited annual result) gives a conservative availability date. |
| 10 | Macro data, RBI/FRED (3.1) | **Reject for v1** | Low expected value at 5–20d horizons; release-timing work not justified yet. |
| 11 | Four canonical data layers (3.2) | **Amend** (P) | Raw: dated Parquet snapshot per download with retrieval time and checksum. Normalised: one validated daily panel in Parquet. Feature layer: computed deterministically, with a versioned spec hash; only the inference-day feature rows are stored with each batch. Forecasts and outcomes go in Postgres. |
| 12 | Data contracts and validation (3.3, 3.6) | **Approve** (C) | Duplicates, OHLC invariants, non-positive prices, stale series, missing sessions (calendar taken from NIFTY's own trading days), zero-volume days (1,690 seen) and jump flags. |
| 13 | Feature families A–D (4.1) | **Approve** (P/E) | Sector context is computed from the universe itself using NSE's industry field; no extra sector-index source needed. Breadth comes from the universe too. Cross-sectional ranks are taken per date. Feature-group ablation decides what stays (E). |
| 14 | Feature family E (fundamentals) | **Amend: narrow earnings family** (P/E) | Features: earnings yield (trailing four-quarter reported EPS ÷ price), year-on-year EPS growth, last earnings surprise vs estimate, sessions since the last result, and **expected earnings in the forecast window** (same quarter last year ± 7 days, so no look-ahead). The last one should matter most for the range forecast, because results days are scheduled volatility. Caveats: the vendor's EPS basis is unknown (it may be adjusted rather than as first reported), and when the estimates were recorded is unknown, so the surprise feature is exploratory. Missing values get explicit missingness flags. Ablation decides what stays. Valuation and quality ratios beyond EPS wait for #9's later source. |
| 15 | Pooled panel model (4.3) | **Approve** (C) | Our evidence: pooled beats per-stock on every test. |
| 16 | Baselines: zero and historical mean (5.1) | **Amend** (C) | Add the baseline that matters: **vol-scaled empirical quantiles**, i.e. the stock's EWMA volatility × the pooled standardised-return quantiles, plus market drift. The 17 Oct review showed naive volatility is hard to beat; a model that does not beat this baseline is not promoted. |
| 17 | Ridge for mean and excess (5.1) | **Approve** (P) | It was the best return signal in our tests (IC 0.037). Its output is shown only if it beats zero and historical mean out of sample. |
| 18 | LightGBM primary + XGBoost challenger (5.1) | **Amend** (P) | **XGBoost only in v1.** It is already a dependency, and since 2.0 one model can fit all seven quantiles (`reg:quantileerror` with a `quantile_alpha` array). LightGBM comes in only if XGBoost beats the baseline and we want a challenger. Comparing two near-identical learners costs effort without changing the decision. |
| 19 | Quantile crossing (5.2) | **Amend** (P) | Sort the quantiles after prediction; record the crossing rate as a metric. |
| 20 | Calibration (6.2) | **Add** (P) | **Conformalised quantile regression** on a rolling calibration window that sits between train and test, so that stated coverage holds. Our vol study needed exactly this: 0.772 coverage raw, 0.798 calibrated. |
| 21 | Walk-forward, purge, embargo (6.1) | **Approve** (C) | Expanding window, monthly refits within the backtest, embargo = horizon. |
| 22 | Untouched final holdout (6.1) | **Amend** (C) | 2023–2026 has been seen in earlier studies. Develop on 2016–2021 and validate once on 2022. Report 2023–2026 as already seen. The real final test is **shadow running** (Gate 4) after the model is frozen. |
| 23 | Metrics (6.2) | **Approve** (C) | Pinball per quantile, coverage at 50/80/90%, crossing rate, MAE/RMSE/bias, Brier and log loss for P(>0) and P(<−5%), each against baselines. Standard errors use non-overlapping origins (block by horizon). |
| 24 | Acceptance thresholds to be set from experiments (6.3) | **Amend** (C) | Set the **decision rules now**, before running. Only noise-level numbers come from data. **Promote** if: (a) pinball loss beats the vol-scaled baseline on validation, with the paired difference positive in ≥ 60% of monthly folds; (b) 80% band coverage within 77–83%; (c) crossing rate < 1% before sorting; (d) no deterioration in either half of the development period. Otherwise **ship the baseline** as the forecast and say so. |
| 25 | EOD batch inference (7.1) | **Approve** (C) | Celery beat at ~18:30 IST on weekdays. It checks that the latest NIFTY session equals today's trading date and retries until a cutoff; otherwise it marks the batch unavailable. Idempotency key: session, model version, config hash. |
| 26 | Forecast schema and immutability (7.2) | **Approve** (C) | New Postgres tables for batches, forecasts and outcomes. Rows are insert-only; corrections are linked revisions. |
| 27 | Agent access (7.3) | **Approve** (C) | Read-only tool `get_return_forecast(ticker, horizon)` returning values, `as_of`, model and feature versions, and status (`ok / stale / not_in_universe / unavailable / baseline_only`). No training or ad-hoc inference on request. |
| 28 | Prediction lifecycle and outcome resolution (8.1) | **Approve** (C) | Daily resolver task; target boundaries are stored with each forecast. |
| 29 | Monitoring and alerts (8.2–8.3) | **Approve, staged** (P) | v1: rolling coverage, pinball against baseline, batch status and universe coverage on the Evaluation page. Drift alerts after enough outcomes have resolved (~3 months). |
| 30 | Monthly retraining, manual promotion, rollback (9) | **Approve, lightweight** (P) | Artifacts on disk (model, calibration offsets, manifest with metrics), a `champion.json` pointer, and a CLI command to promote or roll back. No auto-promotion. No MLOps platform. |
| 31 | Failure handling (10) | **Approve** (C) | As specified. |
| 32 | Compute (11) | **Approve** (verified) | 500 stocks × 10 years ≈ 1.1M rows. Training uses weekly-sampled origins (~230k rows); fits on a laptop in minutes. |
| 33 | Gates 1–5 (12) | **Approve** (C) | Gate 2 uses the rules in #24. Gate 4 runs ≥ 3 months. |
| 34 | Current XGBoost BUY/SELL vote | **Remove** | Already decided 17 Oct and not yet done. Remove it from the `scoring.py` weights, the research prompt, reweight phrases, tests and the UI labels. |
| 35 | Prophet trend factor | **Remove from the verdict** | *Tested 18 Oct* (§5b): no predictive value. Stocks it labels DOWN rose more often over the next 20 days than those labelled UP. Its slope is largely a slower copy of the 3-month-return factor, so the scorecard counts the same thing twice. It also costs a ~1 s Stan fit per stock per question and carries the heaviest dependency in the image. Remove it together with the XGBoost vote (#34). |

## 4. How this relates to the 17 Oct signal plan

The plan's three layers stay. This subsystem implements the **risk layer** (absolute-return distribution) and the forecasting half of the **opportunity layer** (excess return). The plan's **action layer** and its after-costs acceptance test (net excess t ≥ 2 after multiple-testing adjustment, positive each year, holds at 0.40% costs) remain the gate for anything that influences a verdict. The intern's "economic diagnostics are optional" is right for a forecasting subsystem. It is not right for letting a forecast vote, and the plan's gate keeps that distinction.

## 5. Evidence gathered today (NIFTY 500 coverage, Yahoo, 10y to 2026-10-16)

| Check | Result |
|---|---|
| Constituents (NSE list) | 501; 2 with no Yahoo data (DUMMYHEG, BAGMANE) |
| History ≥ 10 / 7 / 5 / 3 / 1 years | 328 / 371 / 404 / 436 / 481 stocks |
| NIFTY 50 index | 2,468 sessions, 2016-10-17 to 2026-10-16 |
| Daily moves > 25% (possible unadjusted corporate actions) | 80 days across 48 stocks |
| Invalid OHLC rows | 0 |
| Zero-volume days | 1,690 |
| Largest industries | Financial Services 98, Capital Goods 70, Healthcare 44, Auto 40 |

Compared with the 47-stock studies, this is about 10× the cross-section. That addresses the plan's main concern, which was statistical power.

## 6. Proposed implementation order (each step stops for review)

| Step | Delivers | Proposal gate |
|---|---|---|
| 0 | Remove the XGBoost vote (#34); shared clean price loader (NaN rows, Wilder RSI) | none |
| 1 | `backend/ml/data`: universe, download, raw snapshot, validation, audit report | Gate 1 |
| 2 | `backend/ml/research`: features, targets, purged walk-forward, baselines, Ridge, XGBoost quantile + conformal calibration, metrics report; promotion decision under rule #24 | Gate 2 |
| 3 | Ledger tables, EOD batch task, outcome resolver, `get_return_forecast` tool, risk-section wording (ranges, not votes) | Gate 3 |
| 4 | Monitoring on the Evaluation page, monthly candidate retrain, promote/rollback CLI | — |
| 5 | Shadow running ≥ 3 months, then release review | Gates 4–5 |

## 7. Questions for sign-off

1. Forecasts go into the risk view only, with no verdict vote, until the after-costs test passes. Agree?
2. NIFTY 500 (today's list, survivorship bias stated) as the v1 universe, or start with NIFTY 200 to keep runs short?
3. Leave fundamentals out of v1. Agree?
4. XGBoost only (no LightGBM) and horizons 5 and 20 in v1. Agree?
5. Do step 0 (remove the XGBoost vote) on this branch as well?
