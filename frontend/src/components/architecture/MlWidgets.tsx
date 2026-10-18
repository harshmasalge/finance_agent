import { useMemo, useState } from 'react';
import { Check, RotateCcw, X } from 'lucide-react';
import { cn } from '../../lib/format';
import { Badge, Button } from '../ui';

/* Small, self-contained calculators that mirror the app's formulas. No data is fetched. */

const signed = (v: number, d = 2) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`;

function Slider({ value, min, max, step, onChange, label, disabled }: {
  value: number; min: number; max: number; step: number; onChange: (v: number) => void; label: string; disabled?: boolean;
}) {
  return (
    <input type="range" aria-label={label} min={min} max={max} step={step} value={value} disabled={disabled}
      onChange={e => onChange(Number(e.target.value))}
      className="h-1.5 w-full cursor-pointer disabled:cursor-not-allowed disabled:opacity-40" style={{ accentColor: 'var(--primary)' }} />
  );
}

/* ------------------------- Signal scorecard ------------------------- */

const FACTORS = [
  { id: 'trend', label: 'Long-term trend', w: 1.5, rule: '+1 above the 50- and 200-day EMAs · 0 between · −1 below both' },
  { id: 'momentum', label: 'Short-term momentum', w: 1, rule: '0.6 × (% vs 20-day EMA ÷ 5) + 0.4 × sign of MACD histogram' },
  { id: 'rsi', label: 'RSI (14)', w: 0.75, rule: '+1 below 30 · −1 above 70 · otherwise (50 − RSI) ÷ 40' },
  { id: 'returns', label: '3-month return', w: 1, rule: 'return ÷ 15%' },
  { id: 'valuation', label: 'Valuation', w: 1, rule: 'PEG bands: < 1 → +1 … > 3 → −1 (P/E bands if growth is unknown)' },
  { id: 'growth', label: 'Revenue growth', w: 0.75, rule: '(growth − 5%) ÷ 15%' },
  { id: 'sentiment', label: 'News sentiment', w: 0.75, rule: '7-day FinBERT average × 2' },
] as const;
type FactorId = typeof FACTORS[number]['id'];
type State = Record<FactorId, { v: number; on: boolean }>;

const make = (vals: number[], off: FactorId[] = []): State =>
  Object.fromEntries(FACTORS.map((f, i) => [f.id, { v: vals[i], on: !off.includes(f.id) }])) as State;

const PRESETS: { label: string; state: State }[] = [
  { label: 'Strong uptrend', state: make([1, 0.7, -0.3, 0.8, 0.4, 0.5, 0.4]) },
  { label: 'Mixed signals', state: make([1, -0.4, 0.5, -0.2, -0.5, 0.3, 0.2]) },
  { label: 'Falling, expensive', state: make([-1, -0.8, 0.6, -0.7, -1, -0.3, -0.5]) },
  { label: 'Thin data', state: make([1, 0.5, 0, 0.6, 0, 0, 0], ['valuation', 'growth', 'sentiment']) },
];

function scorecard(s: State) {
  const on = FACTORS.filter(f => s[f.id].on);
  const totalW = on.reduce((a, f) => a + f.w, 0);
  const allW = FACTORS.reduce((a, f) => a + f.w, 0);
  const score = totalW ? Math.round((on.reduce((a, f) => a + s[f.id].v * f.w, 0) / totalW) * 1000) / 10 : 0;
  const verdict = score >= 15 ? 'BUY' : score <= -15 ? 'SELL' : 'HOLD';
  const dir = Math.sign(score);
  const voting = on.filter(f => Math.abs(s[f.id].v) >= 0.15);
  const agreement = voting.length && dir ? voting.filter(f => s[f.id].v > 0 === dir > 0).length / voting.length : 0.5;
  const coverage = totalW / allW;
  const strength = Math.min(1, Math.abs(score) / 50);
  const raw = Math.min(0.9, Math.round((0.25 + 0.35 * strength + 0.25 * agreement + 0.15 * coverage) * 100) / 100);
  // Same as backend/agent/scoring.py: a scorecard without fundamentals never claims more than 60%.
  const confidence = s.valuation.on || s.growth.on ? raw : Math.min(raw, 0.6);
  return { score, verdict, confidence, coverage, agreement, totalW, contrib: (id: FactorId) => (totalW && s[id].on ? (s[id].v * FACTORS.find(f => f.id === id)!.w / totalW) * 100 : 0) };
}

function Gauge({ score }: { score: number }) {
  const x = (v: number) => 200 + v * 1.85;
  return (
    <svg viewBox="0 -3 400 54" className="block w-full" role="img" aria-label={`Score ${score} on a scale from −100 to +100`}>
      <rect x={x(-100)} y="14" width={x(-15) - x(-100)} height="12" rx="6" style={{ fill: 'color-mix(in oklab, var(--down) 22%, var(--surface))' }} />
      <rect x={x(-15)} y="14" width={x(15) - x(-15)} height="12" style={{ fill: 'var(--surface-3)' }} />
      <rect x={x(15)} y="14" width={x(100) - x(15)} height="12" rx="6" style={{ fill: 'color-mix(in oklab, var(--up) 22%, var(--surface))' }} />
      {[-100, -50, -15, 0, 15, 50, 100].map(t => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1="28" y2="32" style={{ stroke: 'var(--muted)' }} />
          <text x={x(t)} y="46" fontSize="12" textAnchor="middle" style={{ fill: 'var(--muted)' }}>{t > 0 ? `+${t}` : t}</text>
        </g>
      ))}
      <text x={x(-57)} y="9" fontSize="11.5" fontWeight="600" textAnchor="middle" style={{ fill: 'var(--down)' }}>SELL</text>
      <text x={x(0)} y="9" fontSize="11.5" fontWeight="600" textAnchor="middle" style={{ fill: 'var(--muted)' }}>HOLD</text>
      <text x={x(57)} y="9" fontSize="11.5" fontWeight="600" textAnchor="middle" style={{ fill: 'var(--up)' }}>BUY</text>
      <g style={{ transform: `translateX(${x(score)}px)`, transition: 'transform 250ms ease' }}>
        <line x1="0" x2="0" y1="10" y2="30" strokeWidth="2.5" style={{ stroke: 'var(--fg)' }} />
        <circle cx="0" cy="20" r="4.5" style={{ fill: 'var(--fg)' }} />
      </g>
    </svg>
  );
}

export function ScorecardSimulator() {
  const [s, setS] = useState<State>(PRESETS[0].state);
  const r = useMemo(() => scorecard(s), [s]);
  const set = (id: FactorId, patch: Partial<{ v: number; on: boolean }>) => setS(p => ({ ...p, [id]: { ...p[id], ...patch } }));
  const tone = r.verdict === 'BUY' ? 'up' : r.verdict === 'SELL' ? 'down' : 'neutral';

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[12px] font-medium text-muted">Try</span>
          {PRESETS.map(p => (
            <button key={p.label} type="button" onClick={() => setS(p.state)}
              className="rounded-full border border-border bg-surface px-3 py-1 text-[12.5px] font-medium text-fg-2 transition-colors hover:border-border-strong hover:text-fg">
              {p.label}
            </button>
          ))}
        </div>
        <div className="divide-y divide-border rounded-xl border border-border">
          {FACTORS.map(f => {
            const st = s[f.id];
            const c = r.contrib(f.id);
            return (
              <div key={f.id} className={cn('grid grid-cols-[20px_minmax(0,1fr)] gap-x-3 px-3 py-2.5 sm:grid-cols-[20px_minmax(0,1.3fr)_minmax(120px,1fr)_96px] sm:items-center', !st.on && 'opacity-55')}>
                <input type="checkbox" checked={st.on} onChange={e => set(f.id, { on: e.target.checked })}
                  aria-label={`${f.label}: data available`} className="h-4 w-4 cursor-pointer" style={{ accentColor: 'var(--primary)' }} />
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-[13px] font-medium text-fg">
                    {f.label}<span className="rounded bg-surface-2 px-1.5 py-px text-[11px] font-semibold text-muted tabular">×{f.w}</span>
                  </div>
                  <div className="text-[11.5px] leading-snug text-muted">{f.rule}</div>
                </div>
                <div className="col-start-2 mt-2 flex items-center gap-2 sm:col-start-auto sm:mt-0">
                  <Slider label={`${f.label} factor score`} min={-1} max={1} step={0.05} value={st.v} disabled={!st.on} onChange={v => set(f.id, { v })} />
                  <span className={cn('w-11 shrink-0 text-right text-[12.5px] font-semibold tabular', st.v > 0 ? 'text-up' : st.v < 0 ? 'text-down' : 'text-muted')}>{signed(st.v)}</span>
                </div>
                <div className="col-start-2 mt-1.5 sm:col-start-auto sm:mt-0" title="Contribution to the score">
                  <div className="relative h-2 rounded-full bg-surface-2">
                    <span className="absolute top-0 bottom-0 left-1/2 w-px bg-border-strong" />
                    <span className={cn('absolute top-0 bottom-0 rounded-full transition-all duration-200', c >= 0 ? 'bg-up' : 'bg-down')}
                      style={{ left: c >= 0 ? '50%' : `${50 + Math.max(c, -50)}%`, width: `${Math.min(Math.abs(c), 50)}%` }} />
                  </div>
                  <div className="mt-0.5 text-right text-[11px] text-muted tabular">{st.on ? `${signed(c, 1)} pts` : 'no data'}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="space-y-3">
        <div className="rounded-xl border border-border bg-surface-2 p-4">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-[12px] font-medium text-muted">Score</div>
              <div className="text-[32px] font-semibold leading-tight tracking-tight tabular">{r.score > 0 ? '+' : ''}{r.score.toFixed(1)}</div>
            </div>
            <div className="text-right">
              <Badge tone={tone} className="px-2 py-1 text-[13px]">{r.verdict}</Badge>
              <div className="mt-1.5 text-[12px] text-muted">confidence <span className="font-semibold text-fg tabular">{Math.round(r.confidence * 100)}%</span></div>
            </div>
          </div>
          <div className="mt-2"><Gauge score={r.score} /></div>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-[12px]">
            <div className="rounded-lg bg-surface px-2.5 py-1.5"><dt className="text-muted">Data coverage</dt><dd className="font-semibold tabular">{Math.round(r.coverage * 100)}%</dd></div>
            <div className="rounded-lg bg-surface px-2.5 py-1.5"><dt className="text-muted">Agreement</dt><dd className="font-semibold tabular">{Math.round(r.agreement * 100)}%</dd></div>
          </dl>
        </div>
        <div className="rounded-xl border border-border p-4 text-[12.5px] leading-relaxed text-fg-2">
          <div className="mb-1.5 font-semibold text-fg">How it is computed</div>
          <p><span className="font-mono text-[11.5px]">score = Σ(factor × weight) ÷ Σ weight × 100</span>, using only factors with data.</p>
          <p className="mt-1.5">BUY at +15 or more, SELL at −15 or less, otherwise HOLD.</p>
          <p className="mt-1.5">Confidence = 0.25 + 0.35 × strength + 0.25 × agreement + 0.15 × coverage, capped at 90%. Strength is |score| ÷ 50; agreement is the share of factors (|value| ≥ 0.15) pointing the same way as the score.</p>
          <p className="mt-1.5 text-muted">Missing data lowers coverage and confidence instead of being guessed. Untick a factor to see it.</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setS(PRESETS[0].state)}><RotateCcw className="h-3.5 w-3.5" />Reset</Button>
      </div>
    </div>
  );
}

/* ------------------------- Headline matcher examples ------------------------- */

const HEADLINES = [
  { t: 'State Bank of India trims lending rates by 10 bps', ok: true, why: 'Names the company by its full name.' },
  { t: 'SBI raises ₹10,000 crore through infrastructure bonds', ok: true, why: '"SBI" is a known alias, matched as a whole word.' },
  { t: 'SBI Life posts record premium growth in Q2', ok: false, why: '"SBI" followed by "Life" is a different listed company, so it is excluded.' },
  { t: 'SBI Card shares slip after new RBI norms', ok: false, why: '"SBI Card" is excluded for the same reason.' },
  { t: 'Bank stocks rally as Nifty hits a record high', ok: false, why: 'Doesn\'t name the company: market-wide news would blur its score.' },
];

export function HeadlineExamples() {
  const [open, setOpen] = useState<number | null>(2);
  return (
    <div>
      <div className="mb-2 text-[13px] font-semibold text-fg">Which headlines count for SBI (SBIN)? <span className="font-normal text-muted">Made-up examples. Click one.</span></div>
      <ul className="divide-y divide-border rounded-xl border border-border">
        {HEADLINES.map((h, i) => (
          <li key={h.t}>
            <button type="button" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}
              className="flex w-full items-start gap-3 px-3 py-2.5 text-left text-[13px] transition-colors hover:bg-surface-2">
              <span className={cn('mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full', h.ok ? 'bg-up/15 text-up' : 'bg-down/10 text-down')}>
                {h.ok ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
              </span>
              <span className="min-w-0">
                <span className="text-fg">&ldquo;{h.t}&rdquo;</span>
                {open === i && <span className="mt-0.5 block text-[12.5px] text-muted animate-fade-in">{h.ok ? 'Counted. ' : 'Ignored. '}{h.why}</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
