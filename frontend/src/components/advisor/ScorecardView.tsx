import { useState } from 'react';
import { ChevronDown, Info } from 'lucide-react';
import type { Scorecard } from '../../lib/api';
import { cn, tickerLabel } from '../../lib/format';

const VERDICT_TEXT: Record<string, string> = { BUY: 'text-up', SELL: 'text-down', HOLD: 'text-warn' };

/** Horizontal gauge from -100 to +100 with the SELL / BUY thresholds marked. */
function Gauge({ card }: { card: Scorecard }) {
  const pos = (v: number) => `${(v + 100) / 2}%`;
  return (
    <div className="relative mt-3 h-2 rounded-full bg-gradient-to-r from-down/30 via-surface-3 to-up/30">
      <span className="absolute -top-1 h-4 w-px bg-border-strong" style={{ left: pos(card.thresholds.sell) }} />
      <span className="absolute -top-1 h-4 w-px bg-border-strong" style={{ left: pos(card.thresholds.buy) }} />
      <span className={cn('absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface shadow-md transition-[left] duration-700',
        card.verdict === 'BUY' ? 'bg-up' : card.verdict === 'SELL' ? 'bg-down' : 'bg-warn')} style={{ left: pos(Math.max(-100, Math.min(100, card.score))) }} />
      <div className="absolute top-3.5 flex w-full justify-between text-[10px] text-muted tabular">
        <span>−100</span>
        <span className="absolute -translate-x-1/2" style={{ left: pos(card.thresholds.sell) }}>SELL {card.thresholds.sell}</span>
        <span className="absolute -translate-x-1/2" style={{ left: pos(card.thresholds.buy) }}>BUY +{card.thresholds.buy}</span>
        <span>+100</span>
      </div>
    </div>
  );
}

function FactorRow({ f, onCite, citeNum }: { f: Scorecard['factors'][number]; onCite?: (id: string) => void; citeNum?: number }) {
  const w = Math.abs(f.score) * 50;
  return (
    <div className="grid grid-cols-[130px_1fr_44px] items-center gap-3 py-1.5 text-[12.5px] sm:grid-cols-[150px_140px_44px_1fr]">
      <span className="truncate font-medium text-fg-2">{f.label}</span>
      <div className="relative h-1.5 rounded-full bg-surface-2">
        <span className="absolute left-1/2 top-[-3px] h-3 w-px bg-border-strong" />
        <span className={cn('absolute top-0 h-full rounded-full', f.score >= 0 ? 'bg-up' : 'bg-down')}
          style={f.score >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }} />
      </div>
      <span className={cn('text-right font-semibold tabular', f.score > 0.05 ? 'text-up' : f.score < -0.05 ? 'text-down' : 'text-muted')}>
        {f.score > 0 ? '+' : ''}{f.score.toFixed(2)}
      </span>
      <span className="col-span-3 -mt-1 text-muted sm:col-span-1 sm:mt-0">
        {f.reason}
        {f.evidence_id && onCite && citeNum ? (
          <button onClick={() => onCite(f.evidence_id!)} className="ml-1 inline-grid h-4 min-w-4 place-items-center rounded bg-primary/10 px-1 align-middle text-[10px] font-semibold text-primary transition-colors hover:bg-primary hover:text-primary-fg">{citeNum}</button>
        ) : null}
      </span>
    </div>
  );
}

export default function ScorecardView({ card, onCite, citeNumber, defaultOpen = true, compact = false }:
  { card: Scorecard; onCite?: (id: string) => void; citeNumber?: (id: string) => number | undefined; defaultOpen?: boolean; compact?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const sorted = [...card.factors].sort((a, b) => Math.abs(b.score * b.weight) - Math.abs(a.score * a.weight));
  return (
    <div className={cn('rounded-xl border border-border bg-surface', !compact && 'shadow-[var(--shadow-card)]')}>
      <button onClick={() => setOpen(o => !o)} className="flex w-full items-center gap-3 px-4 py-3 text-left">
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted">Signal scorecard · {tickerLabel(card.ticker)}</div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className={cn('text-lg font-bold tabular', VERDICT_TEXT[card.verdict])}>{card.score > 0 ? '+' : ''}{card.score.toFixed(1)}</span>
            <span className="text-[13px] text-muted">→ <span className={cn('font-semibold', VERDICT_TEXT[card.verdict])}>{card.verdict}</span> · {card.factors.length} factors</span>
          </div>
        </div>
        <ChevronDown className={cn('h-4 w-4 text-muted transition-transform duration-200', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="border-t border-border px-4 pb-4 pt-1 animate-fade-in">
          <div className="pb-6"><Gauge card={card} /></div>
          <div className="divide-y divide-border/60">
            {sorted.map(f => <FactorRow key={f.name} f={f} onCite={onCite} citeNum={f.evidence_id ? citeNumber?.(f.evidence_id) : undefined} />)}
          </div>
          {card.missing.length > 0 && <p className="mt-2 text-[12px] text-muted">Not scored (no data): {card.missing.join(', ')}.</p>}
          <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-muted">
            <Info className="mt-px h-3.5 w-3.5 shrink-0" />
            Rule-based, not chosen by the LLM: each factor is scored −1 to +1, weighted, and averaged to −100…+100. ≥ +{card.thresholds.buy} is BUY, ≤ {card.thresholds.sell} is SELL.
          </p>
        </div>
      )}
    </div>
  );
}
