import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Braces, ExternalLink, X } from 'lucide-react';
import type { AnswerPayload, Evidence, Scorecard } from '../../lib/api';
import ScorecardView from './ScorecardView';
import { cn, timeAgo } from '../../lib/format';
import { Badge, Button } from '../ui';
import { citationNumbers, SOURCE_LABELS, toolLabel } from './evidence';

const AGENT_TONE: Record<string, 'primary' | 'warn' | 'up' | 'neutral'> = { 'Research Agent': 'primary', 'Sentiment Agent': 'warn', 'Risk Agent': 'up', 'Scoring Engine': 'neutral' };

const humanKey = (k: string) => k.replace(/_/g, ' ').replace(/\bpct\b/g, '%').replace(/\bcr\b/, '(₹ cr)').replace(/^\w/, c => c.toUpperCase());

function fmtVal(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString('en-IN') : v.toLocaleString('en-IN', { maximumFractionDigits: 3 });
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (Array.isArray(v)) return v.length ? v.map(fmtVal).join(', ') : '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function OutputView({ output }: { output: unknown }) {
  if (!output || typeof output !== 'object') return <pre className="text-xs">{String(output)}</pre>;
  const o = output as Record<string, unknown>;

  if (o.available === false || o.empty === true || o.held === false) {
    return (
      <div className="flex gap-2 rounded-lg border border-warn/25 bg-warn/10 p-3 text-[13px] text-fg-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
        <span>{String(o.message ?? 'No data available.')}</span>
      </div>
    );
  }

  if (Array.isArray(o.headlines)) {
    return (
      <ul className="space-y-2">
        {(o.headlines as Record<string, string>[]).map((h, i) => (
          <li key={i} className="rounded-lg border border-border p-2.5 transition-colors hover:border-border-strong">
            <a href={h.url} target="_blank" rel="noreferrer" className="group flex items-start gap-1.5 text-[13px] font-medium text-fg hover:text-primary">
              <span>{h.title}</span><ExternalLink className="mt-0.5 h-3 w-3 shrink-0 opacity-50 group-hover:opacity-100" />
            </a>
            <div className="mt-1 text-[11px] text-muted">{h.source}{h.published_at ? ` · ${timeAgo(h.published_at)}` : ''}</div>
          </li>
        ))}
      </ul>
    );
  }

  const tableKey = Object.keys(o).find(k => Array.isArray(o[k]) && (o[k] as unknown[]).length > 0 && typeof (o[k] as unknown[])[0] === 'object');
  const scalars = Object.entries(o).filter(([k, v]) => k !== tableKey && k !== 'available' && (v === null || typeof v !== 'object' || (Array.isArray(v) && v.every(x => typeof x !== 'object'))));

  return (
    <div className="space-y-3">
      {scalars.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
          {scalars.map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="truncate text-[11px] text-muted">{humanKey(k)}</dt>
              <dd className="truncate text-[13px] font-medium tabular text-fg" title={fmtVal(v)}>{fmtVal(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {tableKey && (() => {
        const rows = o[tableKey] as Record<string, unknown>[];
        const cols = Object.keys(rows[0]);
        return (
          <div className="overflow-x-auto rounded-lg border border-border">
            <div className="border-b border-border bg-surface-2 px-2.5 py-1.5 text-[11px] font-medium text-muted">{humanKey(tableKey)}</div>
            <table className="w-full text-[12px]">
              <thead><tr className="text-left text-muted">{cols.map(c => <th key={c} className="whitespace-nowrap px-2.5 py-1.5 font-medium">{humanKey(c)}</th>)}</tr></thead>
              <tbody>{rows.map((r, i) => (
                <tr key={i} className="border-t border-border">{cols.map(c => <td key={c} className="whitespace-nowrap px-2.5 py-1.5 tabular">{fmtVal(r[c])}</td>)}</tr>
              ))}</tbody>
            </table>
          </div>
        );
      })()}
    </div>
  );
}

function EvidenceCard({ e, n, active }: { e: Evidence; n: number; active: boolean }) {
  const [raw, setRaw] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (active) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, [active]);
  const inputs = Object.entries(e.input ?? {});
  return (
    <div ref={ref} className={cn('scroll-mt-4 rounded-xl border bg-surface p-4 transition-[border-color,box-shadow] duration-300',
      active ? 'border-primary shadow-[0_0_0_3px_color-mix(in_oklab,var(--primary)_15%,transparent)]' : 'border-border')}>
      <div className="flex items-start gap-3">
        <span className={cn('grid h-6 min-w-6 place-items-center rounded-md px-1 text-[12px] font-semibold tabular', active ? 'bg-primary text-primary-fg' : 'bg-surface-2 text-fg-2')}>{n}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-fg">{toolLabel(e)}</span>
            <Badge tone={AGENT_TONE[e.agent] ?? 'neutral'}>{e.agent.replace(' Agent', '')}</Badge>
          </div>
          <div className="mt-0.5 text-[12px] text-muted">{SOURCE_LABELS[e.tool] ?? 'Tool output'} · {timeAgo(e.created_at)}</div>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={() => setRaw(r => !r)} title={raw ? 'Formatted view' : 'Raw JSON'} aria-label="Toggle raw JSON"
          className={cn(raw && 'bg-surface-2 text-fg')}><Braces className="h-3.5 w-3.5" /></Button>
      </div>
      {inputs.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {inputs.map(([k, v]) => (
            <span key={k} className="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-2">{k}={fmtVal(v)}</span>
          ))}
        </div>
      )}
      <div className="mt-3">
        {raw ? <pre className="max-h-80 overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-fg-2">{JSON.stringify(e.output, null, 2)}</pre>
          : e.tool === 'compute_signal_scorecard' ? <ScorecardView card={e.output as Scorecard} compact />
          : <OutputView output={e.output} />}
      </div>
    </div>
  );
}

export default function EvidencePanel({ payload, activeId, onClose }: { payload: AnswerPayload; activeId: string | null; onClose: () => void }) {
  const nums = citationNumbers(payload);
  const items = [...payload.evidence].sort((a, b) => (nums.get(a.id) ?? 0) - (nums.get(b.id) ?? 0));
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => ev.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <aside className="flex h-full w-full flex-col bg-bg animate-slide-in-right">
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
        <div>
          <div className="text-sm font-semibold">Sources</div>
          <div className="text-[12px] text-muted">{items.length} tool result{items.length === 1 ? '' : 's'} behind this answer</div>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close sources"><X className="h-4 w-4" /></Button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {items.length === 0 ? <p className="text-sm text-muted">This answer did not use any tools.</p>
          : items.map(e => <EvidenceCard key={e.id} e={e} n={nums.get(e.id) ?? 0} active={e.id === activeId} />)}
      </div>
    </aside>
  );
}
