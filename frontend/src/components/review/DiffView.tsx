import { useMemo, useState } from 'react';
import { ArrowRight, ChevronDown, MessageSquareWarning } from 'lucide-react';
import type { FinalAnswer, Scorecard } from '../../lib/api';
import { cn, tickerLabel } from '../../lib/format';
import type { ChangeLogEntry } from './types';

type Op<T> = { kind: 'same' | 'add' | 'del'; value: T };

/** Longest-common-subsequence diff of two sequences. */
function lcsDiff<T>(a: T[], b: T[], eq: (x: T, y: T) => boolean = (x, y) => x === y): Op<T>[] {
  const n = a.length, m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = eq(a[i], b[j]) ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: Op<T>[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (eq(a[i], b[j])) { out.push({ kind: 'same', value: b[j] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ kind: 'del', value: a[i++] });
    else out.push({ kind: 'add', value: b[j++] });
  }
  while (i < n) out.push({ kind: 'del', value: a[i++] });
  while (j < m) out.push({ kind: 'add', value: b[j++] });
  return out;
}

/** Word-level highlight of how `before` became `after`. */
function WordDiff({ before, after }: { before: string; after: string }) {
  const ops = lcsDiff(before.split(/(\s+)/), after.split(/(\s+)/));
  return (
    <span>
      {ops.map((o, i) => o.kind === 'same' ? <span key={i}>{o.value}</span> : o.kind === 'del'
        ? <del key={i} className="rounded-sm bg-down/15 text-down decoration-down/60">{o.value}</del>
        : <ins key={i} className="rounded-sm bg-up/15 text-up no-underline">{o.value}</ins>)}
    </span>
  );
}

type Row = { kind: 'same' | 'add' | 'del' | 'changed'; before?: string; after?: string };

function claimRows(before: string[], after: string[]): Row[] {
  const ops = lcsDiff(before, after);
  const rows: Row[] = [];
  for (let k = 0; k < ops.length; k++) {
    const o = ops[k], nx = ops[k + 1];
    if (o.kind === 'del' && nx?.kind === 'add') { rows.push({ kind: 'changed', before: o.value, after: nx.value }); k++; }
    else if (o.kind === 'same') rows.push({ kind: 'same', before: o.value, after: o.value });
    else if (o.kind === 'del') rows.push({ kind: 'del', before: o.value });
    else rows.push({ kind: 'add', after: o.value });
  }
  return rows;
}

const VERDICT_TEXT: Record<string, string> = { BUY: 'text-up', SELL: 'text-down', HOLD: 'text-warn' };

export interface DiffViewProps {
  before: FinalAnswer;
  after: FinalAnswer;
  beforeCards?: Scorecard[];
  afterCards?: Scorecard[];
  changeLog?: ChangeLogEntry[];
  fromVersion?: number;
  toVersion?: number;
  /** Shown instead of a diff when the agent pushed back on the correction. */
  pushback?: string | null;
  className?: string;
}

/** Claim-level red/green diff between two answer versions, with the scorecard move and the change log. */
export default function DiffView({ before, after, beforeCards = [], afterCards = [], changeLog = [], fromVersion, toVersion, pushback, className }: DiffViewProps) {
  const [showSame, setShowSame] = useState(false);
  const [showLog, setShowLog] = useState(false);

  const sections = useMemo(() => {
    const bMap = new Map(before.sections.map(s => [s.title, s.claims.map(c => c.text)]));
    const titles = [...after.sections.map(s => s.title), ...before.sections.map(s => s.title).filter(t => !after.sections.some(s => s.title === t))];
    return titles.map(title => {
      const a = after.sections.find(s => s.title === title)?.claims.map(c => c.text) ?? [];
      const rows = claimRows(bMap.get(title) ?? [], a);
      return { title, rows, changed: rows.some(r => r.kind !== 'same'), isNew: !bMap.has(title), removed: !after.sections.some(s => s.title === title) };
    });
  }, [before, after]);

  const cardMoves = afterCards.map(c => ({ c, b: beforeCards.find(x => x.ticker === c.ticker) }))
    .filter(({ c, b }) => b && (b.score !== c.score || b.verdict !== c.verdict));
  const changedCount = sections.reduce((n, s) => n + s.rows.filter(r => r.kind !== 'same').length, 0);

  if (pushback) {
    return (
      <div className={cn('flex items-start gap-2.5 rounded-xl border border-warn/25 bg-warn/[0.07] p-3.5 text-[13px] text-fg-2', className)}>
        <MessageSquareWarning className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
        <div><div className="mb-0.5 text-[12px] font-semibold text-warn">Agent pushed back - answer unchanged</div>{pushback}</div>
      </div>
    );
  }

  return (
    <div className={cn('space-y-3 rounded-xl border border-border bg-surface p-3.5', className)}>
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
        {fromVersion != null && toVersion != null && (
          <span className="inline-flex items-center gap-1 font-semibold text-fg-2">v{fromVersion}<ArrowRight className="h-3 w-3" />v{toVersion}</span>
        )}
        <span>{changedCount} claim change{changedCount === 1 ? '' : 's'}</span>
        <span className="ml-auto inline-flex items-center gap-3">
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-down/60" />removed</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-up/60" />added</span>
        </span>
      </div>

      {(before.verdict !== after.verdict || cardMoves.length > 0) && (
        <div className="flex flex-wrap gap-2">
          {before.verdict !== after.verdict && (
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-2.5 py-1 text-[12.5px] font-semibold">
              Verdict <span className={cn('line-through opacity-70', VERDICT_TEXT[before.verdict ?? ''])}>{before.verdict ?? '-'}</span>
              <ArrowRight className="h-3 w-3 text-muted" /><span className={VERDICT_TEXT[after.verdict ?? '']}>{after.verdict ?? '-'}</span>
            </span>
          )}
          {cardMoves.map(({ c, b }) => (
            <span key={c.ticker} className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-2.5 py-1 text-[12.5px] tabular text-fg-2">
              {tickerLabel(c.ticker)} score <span className="text-muted line-through">{b!.score > 0 ? '+' : ''}{b!.score.toFixed(1)}</span>
              <ArrowRight className="h-3 w-3 text-muted" />
              <span className={cn('font-semibold', VERDICT_TEXT[c.verdict])}>{c.score > 0 ? '+' : ''}{c.score.toFixed(1)} {c.verdict}</span>
            </span>
          ))}
        </div>
      )}

      {before.headline !== after.headline && (
        <div className="text-[13.5px] leading-relaxed text-fg">
          <div className="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">Headline</div>
          <WordDiff before={before.headline} after={after.headline} />
        </div>
      )}

      {sections.filter(s => s.changed || showSame).map(s => (
        <div key={s.title}>
          <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
            {s.title}{s.isNew && <span className="rounded bg-up/10 px-1 text-up">new</span>}{s.removed && <span className="rounded bg-down/10 px-1 text-down">removed</span>}
          </div>
          <ul className="space-y-1">
            {s.rows.filter(r => r.kind !== 'same' || showSame).map((r, i) => (
              <li key={i} className={cn('rounded-md border-l-2 px-2.5 py-1 text-[13px] leading-relaxed',
                r.kind === 'same' && 'border-transparent text-muted',
                r.kind === 'add' && 'border-up bg-up/[0.07] text-fg',
                r.kind === 'del' && 'border-down bg-down/[0.07] text-fg-2 line-through decoration-down/50',
                r.kind === 'changed' && 'border-warn bg-surface-2 text-fg')}>
                {r.kind === 'changed' ? <WordDiff before={r.before!} after={r.after!} /> : (r.after ?? r.before)}
              </li>
            ))}
          </ul>
        </div>
      ))}

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-2">
        <button onClick={() => setShowSame(v => !v)} className="text-[12px] font-medium text-muted transition-colors hover:text-fg">
          {showSame ? 'Hide unchanged claims' : 'Show unchanged claims'}
        </button>
        {changeLog.length > 0 && (
          <button onClick={() => setShowLog(v => !v)} className="inline-flex items-center gap-1 text-[12px] font-medium text-muted transition-colors hover:text-fg">
            Change log ({changeLog.length})<ChevronDown className={cn('h-3 w-3 transition-transform', showLog && 'rotate-180')} />
          </button>
        )}
      </div>
      {showLog && (
        <ul className="space-y-1.5 rounded-lg bg-surface-2 p-2.5 text-[12px] animate-fade-in">
          {changeLog.map((e, i) => (
            <li key={i} className="grid gap-0.5">
              <code className="font-mono text-[11px] text-primary">{e.path}</code>
              {(e.before != null || e.after != null) && (
                <span className="text-fg-2">
                  {e.before != null && <span className="text-down line-through decoration-down/50">{e.before.length > 140 ? `${e.before.slice(0, 140)}…` : e.before}</span>}
                  {e.before != null && e.after != null && ' → '}
                  {e.after != null && <span className="text-up">{e.after.length > 140 ? `${e.after.slice(0, 140)}…` : e.after}</span>}
                </span>
              )}
              <span className="text-muted">{e.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
