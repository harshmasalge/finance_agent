// Types for the /evals API (mirror evals/run.py, evals/backtest.py, evals/router.py).

export interface EvalSummary {
  n_cases: number; n_evaluated: number; n_not_run: number;
  case_pass_rate: number | null; routing_accuracy: number | null; ticker_f1: number | null;
  answer_type_accuracy: number | null; schema_validity: number | null;
  claims: number; citation_coverage: number | null; citation_validity: number | null;
  numbers_checked: number; numbers_grounded: number; number_grounding: number | null; claims_fully_grounded: number | null;
  grounding_false_positive_rate: number | null; grounding_control_numbers: number;
  forbidden_pass_rate: number | null; must_include_rate: number | null; n_must_include: number;
  verdict_determinism: number | null; verdict_matches_stored: number | null; n_verdict_matches_stored: number;
  verdict_consistency: number | null; n_verdict_consistency: number;
  rule_checker_pass_rate: number | null; n_rule_checker: number;
  llm_validator_pass_rate: number | null; n_llm_validator: number; llm_validator_revisions: number | null;
  latency_p50_s: number | null; latency_p95_s: number | null; latency_mean_s: number | null;
  total_tokens_mean: number | null; cost_usd_total: number | null;
  judge_faithfulness: number | null; n_judged: number;
  intent_confusion: Record<string, Record<string, number>>;
}

export interface EvalRunMeta {
  run_id: string; mode: 'replay' | 'live'; created_at: string; git_commit: string | null;
  dataset: { path: string; n_cases: number }; fixtures: string | null; judge: boolean; summary: EvalSummary;
}

export interface EvalCheck { name: string; passed: boolean | null; detail: string; value: unknown; gating: boolean; }

export interface EvalCase {
  id: string; question: string; history: string[]; status: 'evaluated' | 'not_run'; reason?: string;
  passed: boolean | null; notes?: string;
  expected: { expected_intent: string; expected_tickers: string[]; expected_answer_type: string };
  actual?: { intent: string | null; tickers: string[]; answer_type: string | null; verdict: string | null; verdict_ticker: string | null; headline: string | null };
  checks?: EvalCheck[];
  metrics?: { claims: number; latency_s: number | null; numbers: number; numbers_grounded: number; grounding_rate: number | null };
  ungrounded?: { claim: string; number: string; citations: string[] }[];
  judge?: { faithfulness: number | null; claims: { claim: string; label: string; reason: string }[] } | null;
  // Combined view (/evals/overview)
  llm?: { provider: string; model: string; label?: string } | null;
  model_key?: string | null; model_label?: string | null; run_id?: string; chat_id?: number | null;
}

export interface EvalRun extends EvalRunMeta { metric_notes: Record<string, string>; cases: EvalCase[]; }

export interface EvalModel { key: string; label: string; n_evaluated: number; n_passed: number; }

/** GET /evals/overview: every dataset case with the latest result per model, across all runs. */
export interface EvalOverview {
  run_id: 'all'; mode: 'combined'; model: string; created_at: string | null;
  models: EvalModel[];
  runs: { run_id: string; mode: string; created_at: string | null; git_commit: string | null }[];
  summary: EvalSummary & { n_results: number };
  metric_notes: Record<string, string>;
  cases: EvalCase[];
}

export interface BacktestBucket {
  verdict: 'BUY' | 'HOLD' | 'SELL' | 'ALL'; count: number; hit_rate: number | null; pct_outperform: number | null;
  mean_excess: number | null; median_excess: number | null; std_excess: number | null; mean_return: number | null;
}

export interface BacktestResult {
  generated_at: string;
  config: { horizon_trading_days: number; rebalances: number; benchmark: string; factors: string[]; hit_rate_definition: string };
  universe: { name: string; n: number; source: string };
  rebalance_dates: string[]; data_end: string; n_observations: number; n_tickers_scored: number;
  buckets: BacktestBucket[];
  spread: { buy_minus_sell_mean_excess: number; ci95: [number, number] | null; dates_with_both: number; dates_buy_beats_sell: number } | null;
  rank_ic: { mean: number | null; n_dates: number; positive_dates: number };
  factor_ic: Record<string, { mean_ic: number | null; n_dates: number; positive_dates: number }>;
  excluded: { ticker: string; date: string; reason: string }[];
  skipped: { ticker: string; reason: string }[];
  caveats: string[];
}

export type RagLatest = { available: false; message?: string } | { available: true; data: Record<string, unknown> };
