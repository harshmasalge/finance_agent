import { useState } from 'react';
import { AlertTriangle, BookOpen, ChevronDown, ShieldAlert, ShieldCheck } from 'lucide-react';
import type { AnswerPayload } from '../../lib/api';
import { cn, tickerLabel } from '../../lib/format';
import { citationNumbers, toolLabel } from './evidence';
import { StepsSummary } from './AgentSteps';
import ScorecardView from './ScorecardView';

const TYPE_LABEL: Record<string, string> = {
  stock_analysis: 'Stock analysis', comparison: 'Comparison', portfolio_health: 'Portfolio health',
  ideas: 'Ideas', sentiment: 'News & sentiment', general: '',
};
const VERDICT_STYLE: Record<string, string> = {
  BUY: 'bg-up/10 text-up border-up/25', SELL: 'bg-down/10 text-down border-down/25', HOLD: 'bg-warn/10 text-warn border-warn/30',
};

/** Tiny formatter for plain-text replies: **bold** and line breaks. */
function RichText({ text }: { text: string }) {
  return (
    <div className="space-y-2 whitespace-pre-wrap">
      {text.split(/\n{2,}/).map((para, i) => (
        <p key={i}>{para.split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
          part.startsWith('**') && part.endsWith('**') ? <strong key={j} className="font-semibold text-fg">{part.slice(2, -2)}</strong> : part)}</p>
      ))}
    </div>
  );
}

export default function AnswerView({ payload, activeCitation, onCite, onOpenSources }:
  { payload: AnswerPayload; activeCitation: string | null; onCite: (id: string) => void; onOpenSources: () => void }) {
  const a = payload.answer;
  const nums = citationNumbers(payload);
  const evidenceById = new Map(payload.evidence.map(e => [e.id, e]));
  const v = payload.validation;
  const [showIssues, setShowIssues] = useState(false);

  if (a.answer_type === 'general') {
    return <div className="text-[15px] leading-relaxed text-fg-2"><RichText text={a.headline} /></div>;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        {TYPE_LABEL[a.answer_type] && <span className="text-[12px] font-medium uppercase tracking-wider text-muted">{TYPE_LABEL[a.answer_type]}</span>}
        {(payload.tickers ?? []).map(t => <span key={t} className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] font-semibold text-fg-2">{tickerLabel(t)}</span>)}
      </div>

      {a.verdict && (
        <div className={cn('flex flex-wrap items-center gap-4 rounded-xl border px-4 py-3', VERDICT_STYLE[a.verdict])}>
          <div>
            <div className="text-[11px] font-medium uppercase tracking-wider opacity-80">Verdict{a.verdict_ticker ? ` · ${tickerLabel(a.verdict_ticker)}` : ''}</div>
            <div className="text-xl font-bold tracking-tight">{a.verdict}</div>
          </div>
          {a.confidence != null && (
            <div className="ml-auto min-w-[160px]">
              <div className="flex justify-between text-[11px] font-medium opacity-80"><span>Confidence</span><span className="tabular">{Math.round(a.confidence * 100)}%</span></div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-current/15">
                <div className="h-full rounded-full bg-current transition-[width] duration-700" style={{ width: `${a.confidence * 100}%` }} />
              </div>
            </div>
          )}
        </div>
      )}

      <p className="text-[15.5px] font-medium leading-relaxed text-fg">{a.headline}</p>

      {(payload.scorecards ?? []).length > 0 && (
        <div className={cn('grid gap-3', (payload.scorecards ?? []).length > 1 && 'lg:grid-cols-1')}>
          {[...(payload.scorecards ?? [])].sort((x, y) => y.score - x.score).map((c, i) => (
            <ScorecardView key={c.ticker} card={c} defaultOpen={i === 0} onCite={onCite} citeNumber={id => nums.get(id)} />
          ))}
        </div>
      )}

      {a.sections.map((s, i) => (
        <section key={i}>
          <h4 className="mb-2 text-[12px] font-semibold uppercase tracking-wider text-muted">{s.title}</h4>
          <ul className="space-y-2">
            {s.claims.map((c, j) => (
              <li key={j} className="flex gap-2.5 text-[14.5px] leading-relaxed text-fg-2">
                <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-muted" />
                <span>
                  {c.text}
                  {c.citations.filter(id => nums.has(id)).map(id => {
                    const e = evidenceById.get(id);
                    return (
                      <button key={id} onClick={() => onCite(id)}
                        title={e ? `${toolLabel(e)} · ${e.agent}` : id}
                        className={cn('relative -top-px ml-1 inline-grid h-[18px] min-w-[18px] place-items-center rounded-[5px] px-1 align-middle text-[10.5px] font-semibold tabular transition-all duration-150',
                          activeCitation === id ? 'bg-primary text-primary-fg' : 'bg-primary/10 text-primary hover:bg-primary hover:text-primary-fg')}>
                        {nums.get(id)}
                      </button>
                    );
                  })}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}

      {a.data_gaps.length > 0 && (
        <div className="rounded-xl border border-warn/25 bg-warn/[0.07] p-3.5">
          <div className="mb-1 flex items-center gap-1.5 text-[12px] font-semibold text-warn"><AlertTriangle className="h-3.5 w-3.5" />Data gaps</div>
          <ul className="space-y-0.5 text-[13px] text-fg-2">{a.data_gaps.map((g, i) => <li key={i}>• {g}</li>)}</ul>
        </div>
      )}

      <div className="-mb-2 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        {v && v.status !== 'skipped' && (
          v.status === 'passed' ? (
            <span className="inline-flex items-center gap-1.5 rounded-md bg-up/10 px-2 py-1 text-[12px] font-medium text-up">
              <ShieldCheck className="h-3.5 w-3.5" />Verified · {v.cited_claims}/{v.claims} claims cited
            </span>
          ) : (
            <button onClick={() => setShowIssues(s => !s)} className="inline-flex items-center gap-1.5 rounded-md bg-warn/10 px-2 py-1 text-[12px] font-medium text-warn transition-colors hover:bg-warn/15">
              <ShieldAlert className="h-3.5 w-3.5" />Checker notes ({v.issues.length})<ChevronDown className={cn('h-3 w-3 transition-transform', showIssues && 'rotate-180')} />
            </button>
          )
        )}
        {payload.evidence.length > 0 && (
          <button onClick={onOpenSources} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] font-medium text-fg-2 transition-colors hover:bg-surface-2 hover:text-fg">
            <BookOpen className="h-3.5 w-3.5" />{payload.evidence.length} sources
          </button>
        )}
      </div>
      {showIssues && v && (
        <ul className="-mt-2 space-y-1 rounded-lg bg-surface-2 p-3 text-[12.5px] text-fg-2 animate-fade-in">
          {v.issues.map((iss, i) => <li key={i}>• {iss}</li>)}
          <li className="pt-1 text-[11px] text-muted">The answer was revised once; these points remained after the Validation Agent's review.</li>
        </ul>
      )}
      <StepsSummary steps={payload.steps ?? []} evidence={payload.evidence} duration={payload.duration_s} onOpenTool={onCite} />
    </div>
  );
}
