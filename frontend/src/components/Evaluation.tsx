import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { BookOpen, CheckCircle2, ChevronDown, ChevronRight, CircleDashed, FlaskConical, LineChart as LineIcon, MessageSquare, MinusCircle, XCircle } from 'lucide-react';
import { api } from '../lib/api';
import { cn } from '../lib/format';
import { useChartColors } from '../lib/theme';
import { Badge, Card, CardHeader, EmptyState, PageHeader, Segmented, Select, Skeleton, Stat } from './ui';
import type { BacktestBucket, BacktestResult, EvalCase, EvalCheck, EvalOverview, RagLatest } from './evaluation/types';
import { useRouter } from '../lib/router';

// ---------- formatting ----------
const pct = (v: number | null | undefined, d = 0) => (v == null ? 'n/a' : `${(v * 100).toFixed(d)}%`);
const pp = (v: number | null | undefined, d = 2) => (v == null ? 'n/a' : `${v > 0 ? '+' : ''}${v.toFixed(d)} pp`);
const sec = (v: number | null | undefined) => (v == null ? 'n/a' : `${v.toFixed(1)}s`);
const num = (v: number | null | undefined, d = 2) => (v == null ? 'n/a' : `${v > 0 ? '+' : ''}${v.toFixed(d)}`);
const frac = (k: number | null | undefined, n: number) => (k == null || !n ? '' : `${Math.round(k * n)}/${n}`);

const CHECK_LABELS: Record<string, string> = {
  routing: 'Routing (intent)', tickers: 'Ticker extraction', answer_type: 'Answer type', schema: 'Schema (FinalAnswer)',
  citation_coverage: 'Citation coverage', citation_validity: 'Citation validity', number_grounding: 'Number grounding',
  forbidden_content: 'Forbidden content', must_include: 'Required content', verdict_consistency: 'Verdict = scorecard',
  rule_checker: 'Rule-based checker', llm_validator: 'LLM validator (recorded)', judge_faithfulness: 'LLM judge faithfulness',
};

function CheckIcon({ passed }: { passed: boolean | null }) {
  if (passed === true) return <CheckCircle2 className="h-4 w-4 shrink-0 text-up" aria-label="passed" />;
  if (passed === false) return <XCircle className="h-4 w-4 shrink-0 text-down" aria-label="failed" />;
  return <MinusCircle className="h-4 w-4 shrink-0 text-muted" aria-label="not applicable" />;
}

function StatusBadge({ c }: { c: EvalCase }) {
  if (c.status === 'not_run') return <Badge>Not run</Badge>;
  return c.passed ? <Badge tone="up">Pass</Badge> : <Badge tone="down">Fail</Badge>;
}

// ---------- page ----------
export default function Evaluation() {
  const [model, setModel] = useState<string>(() => {
    try { return localStorage.getItem('finsight-evals-model') || 'all'; } catch { return 'all'; }
  });
  const [data, setData] = useState<EvalOverview | null>(null);
  const [backtest, setBacktest] = useState<BacktestResult | null | 'missing'>(null);
  const [rag, setRag] = useState<RagLatest | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<BacktestResult>('/evals/backtest/latest').then(setBacktest).catch(() => setBacktest('missing'));
    api<RagLatest>('/evals/rag/latest').then(setRag).catch(() => setRag({ available: false }));
  }, []);

  useEffect(() => {
    let live = true;
    api<EvalOverview>(`/evals/overview?model=${encodeURIComponent(model)}`)
      .then(d => { if (live) { setData(d); setError(null); } })
      .catch(e => {
        if (!live) return;
        if (model !== 'all') { setModel('all'); return; } // that model has no results any more
        setError(String(e.message ?? e));
      });
    return () => { live = false; };
  }, [model]);

  const pick = (m: string) => {
    setModel(m);
    try { localStorage.setItem('finsight-evals-model', m); } catch { /* ignore */ }
  };
  const total = data?.models.reduce((n, m) => n + m.n_evaluated, 0) ?? 0;

  return (
    <div className="mx-auto max-w-[1280px] px-6 py-8 lg:px-10">
      <PageHeader title="Evaluation"
        subtitle="How we know it works: answer-quality metrics on real agent answers, and a backtest of the signal scorecard"
        actions={data && data.models.length > 0 ? (
          <Select aria-label="Filter by model" value={model} onChange={e => pick(e.target.value)} className="w-[300px]">
            <option value="all">All models · {total} results</option>
            {data.models.map(m => <option key={m.key} value={m.key}>{m.label} · {m.n_passed}/{m.n_evaluated} passed</option>)}
          </Select>
        ) : undefined} />

      {data === null && !error ? <KpiSkeleton /> : !data || data.models.length === 0 ? (
        <Card><EmptyState icon={<FlaskConical className="h-5 w-5" />} title="No eval results yet"
          body={error ?? 'Ask the dataset questions in the advisor and score them, or run `python -m evals.run --mode replay`.'} /></Card>
      ) : <RunView run={data} />}

      <div className="mt-6 grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2"><BacktestCard bt={backtest} /></div>
        <RagCard rag={rag} />
      </div>
    </div>
  );
}

function KpiSkeleton() {
  return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">{[0, 1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-[118px]" />)}</div>;
}

// ---------- run ----------
function RunView({ run }: { run: EvalOverview }) {
  const s = run.summary;
  const label = run.model === 'all' ? 'All models' : run.models.find(m => m.key === run.model)?.label ?? run.model;
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-[13px] text-muted">
        <Badge tone="primary">{label}</Badge>
        <span>{s.n_cases - s.n_not_run} of {s.n_cases} dataset cases scored</span>
        {run.model === 'all' && s.n_results > s.n_cases - s.n_not_run && <span>· {s.n_results} answers (some cases answered by several models)</span>}
        {s.n_not_run > 0 && <span>· {s.n_not_run} not run yet</span>}
        <span>· from {run.runs.length} run{run.runs.length === 1 ? '' : 's'}</span>
        {run.created_at && <span>· latest {new Date(run.created_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</span>}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <Stat label="Routing accuracy" value={pct(s.routing_accuracy)} sub={<span className="text-muted">{frac(s.routing_accuracy, s.n_evaluated)} intents · ticker F1 {pct(s.ticker_f1)}</span>} />
        <Stat label="Citation coverage" value={pct(s.citation_coverage)} sub={<span className="text-muted">{s.claims} claims · {pct(s.citation_validity)} ids valid</span>} />
        <Stat label="Number grounding" value={pct(s.number_grounding)}
          sub={<span className="text-muted">{s.numbers_grounded}/{s.numbers_checked} numbers · false-positive control {pct(s.grounding_false_positive_rate, 1)}</span>} />
        <Stat label="Checker pass" value={pct(s.rule_checker_pass_rate)}
          sub={<span className="text-muted">rule checker {frac(s.rule_checker_pass_rate, s.n_rule_checker)} · LLM validator {frac(s.llm_validator_pass_rate, s.n_llm_validator)}</span>} />
        <Stat label="Latency p50 / p95" value={<>{sec(s.latency_p50_s)}<span className="text-muted"> / </span>{sec(s.latency_p95_s)}</>}
          sub={<span className="text-muted">end-to-end per answer · tokens {s.total_tokens_mean == null ? 'not recorded' : Math.round(s.total_tokens_mean)}</span>} />
        <Stat label="Case pass rate" value={pct(s.case_pass_rate)} sub={<span className="text-muted">all gating checks · {frac(s.case_pass_rate, s.n_evaluated)} cases</span>} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2"><CaseTable cases={run.cases} showModel={run.model === 'all'} /></div>
        <MetricDetails run={run} />
      </div>
    </>
  );
}

function MetricDetails({ run }: { run: EvalOverview }) {
  const s = run.summary;
  const rows: { key: string; label: string; value: string; n?: string }[] = [
    { key: 'schema_validity', label: 'Schema validity', value: pct(s.schema_validity) },
    { key: 'answer_type', label: 'Answer type accuracy', value: pct(s.answer_type_accuracy) },
    { key: 'claims_fully_grounded', label: 'Claims fully grounded', value: pct(s.claims_fully_grounded) },
    { key: 'forbidden', label: 'No forbidden content', value: pct(s.forbidden_pass_rate) },
    { key: 'must_include', label: 'Required content present', value: pct(s.must_include_rate), n: `n=${s.n_must_include}` },
    { key: 'verdict_determinism', label: 'Scorecard determinism', value: pct(s.verdict_determinism) },
    { key: 'verdict_matches_stored', label: 'Scorecard reproduces stored', value: pct(s.verdict_matches_stored), n: `n=${s.n_verdict_matches_stored}` },
    { key: 'verdict_consistency', label: 'Answer verdict = scorecard', value: pct(s.verdict_consistency), n: `n=${s.n_verdict_consistency}` },
    { key: 'llm_validator_revisions', label: 'Answers revised by validator', value: pct(s.llm_validator_revisions), n: `n=${s.n_llm_validator}` },
    { key: 'judge', label: 'LLM-judge faithfulness', value: s.n_judged ? pct(s.judge_faithfulness) : 'not run', n: s.n_judged ? `n=${s.n_judged}` : undefined },
  ];
  const notes = run.metric_notes ?? {};
  return (
    <Card className="h-full">
      <CardHeader title="All metrics" subtitle="Rates are over the cases where each metric applies" />
      <dl className="divide-y divide-border px-5 pb-4">
        {rows.map(r => (
          <div key={r.key} className="flex items-baseline justify-between gap-3 py-2 text-[13px]">
            <dt className="text-fg-2">{r.label}{r.n && <span className="ml-1.5 text-[11px] text-muted">{r.n}</span>}</dt>
            <dd className="tabular font-medium text-fg">{r.value}</dd>
          </div>
        ))}
      </dl>
      <details className="border-t border-border px-5 py-3 text-[12.5px] text-muted">
        <summary className="font-medium text-fg-2">Definitions</summary>
        <ul className="mt-2 space-y-1.5">
          {Object.entries(notes).map(([k, v]) => <li key={k}><span className="font-mono text-[11.5px] text-fg-2">{k}</span>: {v}</li>)}
        </ul>
      </details>
    </Card>
  );
}

type CaseFilter = 'all' | 'scored' | 'failed' | 'not_run';

function CaseTable({ cases, showModel }: { cases: EvalCase[]; showModel: boolean }) {
  const [filter, setFilter] = useState<CaseFilter>('scored');
  const [open, setOpen] = useState<string | null>(null);
  const shown = useMemo(() => cases.filter(c =>
    filter === 'all' || (filter === 'scored' && c.status === 'evaluated') || (filter === 'failed' && c.passed === false) ||
    (filter === 'not_run' && c.status === 'not_run')), [cases, filter]);
  const count = (f: CaseFilter) => cases.filter(c => f === 'all' || (f === 'scored' && c.status === 'evaluated') ||
    (f === 'failed' && c.passed === false) || (f === 'not_run' && c.status === 'not_run')).length;

  return (
    <Card>
      <CardHeader title="Test cases" subtitle="Click a case to see every check"
        action={<Segmented value={filter} onChange={setFilter} options={[
          { value: 'scored', label: `Scored (${count('scored')})` }, { value: 'failed', label: `Failed (${count('failed')})` },
          { value: 'not_run', label: `Not run (${count('not_run')})` }, { value: 'all', label: `All (${count('all')})` }]} />} />
      <div className="overflow-x-auto px-2 pb-3">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-border text-left text-[11.5px] font-medium uppercase tracking-wide text-muted">
              <th className="w-6 px-2 py-2" /><th className="px-2 py-2">Case</th><th className="px-2 py-2">Intent</th>
              {showModel && <th className="px-2 py-2">Model</th>}
              <th className="px-2 py-2">Checks</th><th className="px-2 py-2 text-right">Latency</th><th className="px-2 py-2 text-right">Result</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && <tr><td colSpan={showModel ? 7 : 6} className="px-2 py-8 text-center text-muted">No cases in this view</td></tr>}
            {shown.map(c => {
              const gating = (c.checks ?? []).filter(k => k.gating && k.passed !== null);
              const ok = gating.filter(k => k.passed).length;
              const rowKey = `${c.id}|${c.model_key ?? ''}`;
              const isOpen = open === rowKey;
              const intentOk = c.actual ? c.actual.intent === c.expected.expected_intent : null;
              return (
                <Fragment key={rowKey}>
                  <tr className={cn('cursor-pointer border-b border-border transition-colors hover:bg-surface-2', isOpen && 'bg-surface-2')}
                    onClick={() => setOpen(isOpen ? null : rowKey)} aria-expanded={isOpen}>
                    <td className="px-2 py-2.5 text-muted">{isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</td>
                    <td className={cn('px-2 py-2.5', showModel ? 'max-w-[240px]' : 'max-w-[340px]')}>
                      <div className="truncate font-medium text-fg">{c.question}</div>
                      <div className="truncate text-[11.5px] text-muted">{c.id}{c.history.length > 0 && ` · follow-up to "${c.history[c.history.length - 1]}"`}</div>
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5">
                      <span className="text-fg-2">{c.expected.expected_intent}</span>
                      {c.actual && intentOk === false && <span className="text-down"> → {c.actual.intent}</span>}
                    </td>
                    {showModel && <td className="max-w-[130px] px-2 py-2.5 text-[12px] leading-tight text-fg-2" title={c.model_label ?? ''}>{c.model_label?.split(' · ')[0] ?? '—'}</td>}
                    <td className="whitespace-nowrap px-2 py-2.5 tabular text-fg-2">{c.status === 'evaluated' ? `${ok}/${gating.length}` : '—'}</td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-right tabular text-fg-2">{c.metrics ? sec(c.metrics.latency_s) : '—'}</td>
                    <td className="px-2 py-2.5 text-right"><StatusBadge c={c} /></td>
                  </tr>
                  {isOpen && <tr className="border-b border-border bg-surface-2/50"><td colSpan={showModel ? 7 : 6} className="px-4 py-4"><CaseDetail c={c} /></td></tr>}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function CaseDetail({ c }: { c: EvalCase }) {
  const { linkClick } = useRouter();
  if (c.status === 'not_run') {
    return (
      <div className="flex items-start gap-2 text-[13px] text-muted">
        <CircleDashed className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <p>{c.reason}</p>
          <p className="mt-1">Expected: <span className="text-fg-2">{c.expected.expected_intent}</span>
            {c.expected.expected_tickers.length > 0 && <> · <span className="font-mono text-fg-2">{c.expected.expected_tickers.join(', ')}</span></>}
            {' '}· {c.expected.expected_answer_type}</p>
          {c.notes && <p className="mt-1">{c.notes}</p>}
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-4 text-[13px]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
        {c.model_label && <span>Answered by <span className="font-medium text-fg-2">{c.model_label}</span></span>}
        {c.run_id && <span>run <span className="font-mono">{c.run_id}</span></span>}
        {c.chat_id && (
          <a href={`/advisor/${c.chat_id}`} onClick={linkClick(`/advisor/${c.chat_id}`)}
            className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
            <MessageSquare className="h-3.5 w-3.5" />Open the chat
          </a>
        )}
      </div>
      {c.actual?.headline && <p className="text-fg-2">“{c.actual.headline}”</p>}
      <ul className="grid gap-x-6 gap-y-2 md:grid-cols-2">
        {(c.checks ?? []).map((k: EvalCheck) => (
          <li key={k.name} className="flex items-start gap-2">
            <CheckIcon passed={k.passed} />
            <div className="min-w-0">
              <span className="font-medium text-fg">{CHECK_LABELS[k.name] ?? k.name}</span>
              {!k.gating && <span className="ml-1.5 text-[11px] text-muted">(informational)</span>}
              <div className="break-words text-[12px] text-muted">{k.detail}</div>
            </div>
          </li>
        ))}
      </ul>
      {(c.ungrounded?.length ?? 0) > 0 && (
        <div>
          <div className="mb-1 text-[12px] font-medium text-fg-2">Numbers not found in the cited evidence</div>
          <ul className="space-y-1 text-[12px] text-muted">
            {c.ungrounded!.map((u, i) => <li key={i}><span className="font-mono text-down">{u.number}</span> in “{u.claim}” <span className="font-mono">[{u.citations.join(', ')}]</span></li>)}
          </ul>
        </div>
      )}
      {c.notes && <p className="text-[12px] text-muted">Note: {c.notes}</p>}
    </div>
  );
}

// ---------- backtest ----------
function BacktestCard({ bt }: { bt: BacktestResult | null | 'missing' }) {
  const colors = useChartColors();
  if (bt === null) return <Skeleton className="h-[420px]" />;
  if (bt === 'missing') {
    return <Card><CardHeader title="Scorecard backtest" />
      <EmptyState icon={<LineIcon className="h-5 w-5" />} title="Not run yet" body="Run `python -m evals.backtest` to score NIFTY 50 stocks monthly over the last year." /></Card>;
  }
  const order: BacktestBucket['verdict'][] = ['BUY', 'HOLD', 'SELL', 'ALL'];
  const buckets = order.map(v => bt.buckets.find(b => b.verdict === v)).filter((b): b is BacktestBucket => !!b);
  const data = buckets.map(b => ({ name: b.verdict === 'ALL' ? 'All stocks' : b.verdict, value: b.mean_excess ?? 0, b }));
  const first = bt.rebalance_dates[0], last = bt.rebalance_dates[bt.rebalance_dates.length - 1];
  const sp = bt.spread;

  return (
    <Card>
      <CardHeader title="Scorecard backtest · price factors only"
        subtitle={`${bt.universe.name} · ${bt.rebalance_dates.length} monthly rebalances ${first} → ${last} · ${bt.config.horizon_trading_days}-trading-day excess return vs NIFTY 50`} />
      <div className="grid gap-4 px-5 pb-2 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <div className="mb-1 text-[12px] font-medium text-muted">Mean excess return by verdict (pp)</div>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={colors.grid} vertical={false} />
                <XAxis dataKey="name" stroke={colors.axis} fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke={colors.axis} fontSize={11} tickLine={false} axisLine={false} width={44} tickFormatter={v => `${Number(v).toFixed(1)}`} />
                <ReferenceLine y={0} stroke={colors.axis} />
                <Tooltip cursor={{ fill: colors.grid }}
                  contentStyle={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: 10, fontSize: 12, color: colors.fg }}
                  labelStyle={{ color: colors.axis, marginBottom: 4 }}
                  formatter={(_v, _n, item) => {
                    const b = (item?.payload as { b: BacktestBucket }).b;
                    return [`${pp(b.mean_excess)} mean · ${pp(b.median_excess)} median · n=${b.count}`, 'Excess return'];
                  }} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={48} isAnimationActive={false}>
                  {data.map(d => <Cell key={d.name} fill={d.name === 'All stocks' ? colors.axis : d.value >= 0 ? colors.up : colors.down} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="overflow-x-auto lg:col-span-3">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border text-left text-[11.5px] font-medium uppercase tracking-wide text-muted">
                <th className="py-2 pr-2">Bucket</th><th className="px-2 py-2 text-right">Count</th><th className="px-2 py-2 text-right">Hit rate</th>
                <th className="px-2 py-2 text-right">Beat index</th><th className="px-2 py-2 text-right">Mean excess</th><th className="py-2 pl-2 text-right">Median excess</th>
              </tr>
            </thead>
            <tbody className="tabular">
              {buckets.map(b => (
                <tr key={b.verdict} className={cn('border-b border-border', b.verdict === 'ALL' && 'font-medium')}>
                  <td className="py-2 pr-2">{b.verdict === 'ALL' ? 'All stocks (baseline)' : <Badge tone={b.verdict === 'BUY' ? 'up' : b.verdict === 'SELL' ? 'down' : 'neutral'}>{b.verdict}</Badge>}</td>
                  <td className="px-2 py-2 text-right">{b.count}</td>
                  <td className="px-2 py-2 text-right">{pct(b.hit_rate, 1)}</td>
                  <td className="px-2 py-2 text-right">{pct(b.pct_outperform, 1)}</td>
                  <td className="px-2 py-2 text-right">{pp(b.mean_excess)}</td>
                  <td className="py-2 pl-2 text-right">{pp(b.median_excess)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[12px] text-muted">Hit rate: BUY beats the index, SELL lags it. {bt.n_observations} stock-months, {bt.n_tickers_scored} stocks.</p>
        </div>
      </div>

      <div className="grid gap-4 border-t border-border px-5 py-4 text-[13px] md:grid-cols-2">
        <div>
          <div className="mb-1.5 font-medium text-fg">Does the score rank stocks?</div>
          {sp && <p className="text-fg-2">BUY minus SELL: <span className="tabular font-medium">{pp(sp.buy_minus_sell_mean_excess)}</span>
            {sp.ci95 && <span className="text-muted"> (95% CI {pp(sp.ci95[0])} to {pp(sp.ci95[1])}, bootstrapped over dates)</span>};
            BUY beat SELL in {sp.dates_buy_beats_sell} of {sp.dates_with_both} months.</p>}
          <p className="mt-1 text-fg-2">Mean rank IC of the score: <span className="tabular font-medium">{num(bt.rank_ic.mean, 3)}</span>
            <span className="text-muted"> (positive in {bt.rank_ic.positive_dates} of {bt.rank_ic.n_dates} months)</span></p>
        </div>
        <div>
          <div className="mb-1.5 font-medium text-fg">Per-factor rank IC</div>
          <ul className="space-y-1">
            {Object.entries(bt.factor_ic).map(([k, v]) => (
              <li key={k} className="flex justify-between gap-3 text-fg-2">
                <span className="capitalize">{k === 'returns' ? '3-month return' : k}</span>
                <span className="tabular"><span className="font-medium text-fg">{num(v.mean_ic, 3)}</span><span className="text-muted"> · {v.positive_dates}/{v.n_dates} months &gt; 0</span></span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <details className="border-t border-border px-5 py-3 text-[12.5px] text-muted">
        <summary className="font-medium text-fg-2">Caveats ({bt.caveats.length}){bt.excluded.length > 0 && ` · ${bt.excluded.length} stock-months excluded for data breaks`}</summary>
        <ul className="mt-2 list-disc space-y-1.5 pl-5">{bt.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
      </details>
    </Card>
  );
}

// ---------- RAG ----------
const RAG_KEYS: [string, string, 'pct' | 'num'][] = [
  ['recall_at_1', 'Recall@1', 'pct'], ['recall@1', 'Recall@1', 'pct'], ['recall_at_5', 'Recall@5', 'pct'], ['recall@5', 'Recall@5', 'pct'],
  ['mrr', 'MRR', 'num'], ['table_extraction_accuracy', 'Table extraction', 'pct'], ['table_spot_check', 'Table extraction', 'pct'],
  ['pages_per_sec', 'Ingest pages/s', 'num'], ['ingest_pages_per_sec', 'Ingest pages/s', 'num'], ['n_questions', 'Questions', 'num'],
];

function flattenNumbers(obj: Record<string, unknown>, prefix = ''): [string, number][] {
  const out: [string, number][] = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (typeof v === 'number' && Number.isFinite(v)) out.push([key, v]);
    else if (v && typeof v === 'object' && !Array.isArray(v) && !prefix) out.push(...flattenNumbers(v as Record<string, unknown>, key));
  }
  return out;
}

function RagCard({ rag }: { rag: RagLatest | null }) {
  let body: ReactNode;
  if (rag === null) body = <div className="px-5 pb-5"><Skeleton className="h-40" /></div>;
  else if (!rag.available) {
    body = <EmptyState icon={<BookOpen className="h-5 w-5" />} title="Not run yet" body="The filings retrieval benchmark (recall@k, MRR) appears here once it has been run." />;
  } else {
    const flat = flattenNumbers(rag.data);
    const byKey = new Map(flat.map(([k, v]) => [k.split('.').pop()!.toLowerCase(), v]));
    const seen = new Set<string>();
    const known = RAG_KEYS.filter(([k, label]) => byKey.has(k) && !seen.has(label) && seen.add(label));
    const rows = known.length
      ? known.map(([k, label, kind]) => [label, kind === 'pct' && byKey.get(k)! <= 1 ? pct(byKey.get(k)!, 1) : String(Number(byKey.get(k)!.toFixed(3)))])
      : flat.slice(0, 10).map(([k, v]) => [k, String(Number(v.toFixed(3)))]);
    body = (
      <dl className="divide-y divide-border px-5 pb-4">
        {rows.map(([l, v]) => <div key={l} className="flex justify-between py-2 text-[13px]"><dt className="text-fg-2">{l}</dt><dd className="tabular font-medium">{v}</dd></div>)}
      </dl>
    );
  }
  return (
    <Card className="h-full">
      <CardHeader title="Filings retrieval (RAG)" subtitle="Benchmark of the knowledge-base search" />
      {body}
    </Card>
  );
}
