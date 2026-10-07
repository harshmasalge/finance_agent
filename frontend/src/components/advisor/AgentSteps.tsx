import { useState } from 'react';
import { Check, ChevronRight, Loader2, Wrench } from 'lucide-react';
import type { Evidence, Step, ToolCall } from '../../lib/api';
import { cn } from '../../lib/format';
import { TOOL_LABELS } from './evidence';

/** Merge step events (running/done) into one row per node, in first-seen order. */
export function mergeSteps(events: Step[]): Step[] {
  const order: string[] = [];
  const latest = new Map<string, Step>();
  for (const s of events) {
    if (!latest.has(s.node)) order.push(s.node);
    const prev = latest.get(s.node);
    latest.set(s.node, { ...prev, ...s, detail: s.detail || prev?.detail, tools: s.tools?.length ? s.tools : prev?.tools });
  }
  return order.map(n => latest.get(n)!);
}

const AGENT_FOR_NODE: Record<string, string> = {
  research_node: 'Research Agent', sentiment_node: 'Sentiment Agent', risk_node: 'Risk Agent', synthesis_node: 'Scoring Engine',
};

/** Older answers were saved without per-step tool lists - rebuild them from the evidence. */
function toolsFor(step: Step, evidence?: Evidence[]): ToolCall[] {
  if (step.tools?.length) return step.tools;
  const agent = AGENT_FOR_NODE[step.node];
  return (evidence ?? []).filter(e => e.agent === agent).map(e => ({ id: e.id, tool: e.tool, input: e.input }));
}

function argSummary(input: Record<string, unknown>) {
  const v = Object.entries(input ?? {}).filter(([k]) => k !== 'args').map(([, val]) => (Array.isArray(val) ? `${val.length} items` : String(val)));
  return v.join(', ');
}

function ToolChip({ call, onClick }: { call: ToolCall; onClick?: () => void }) {
  const label = TOOL_LABELS[call.tool] ?? call.tool;
  const args = argSummary(call.input);
  const body = (
    <>
      <Wrench className="h-3 w-3 shrink-0 opacity-60" />
      <span className="font-medium">{label}</span>
      {args && <span className="truncate font-mono text-[10.5px] opacity-70">({args})</span>}
    </>
  );
  return onClick ? (
    <button onClick={onClick} title={`Open ${label} output`}
      className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1 text-[11.5px] text-fg-2 transition-all duration-150 hover:-translate-y-px hover:border-primary/40 hover:bg-primary/5 hover:text-primary active:translate-y-0">
      {body}
    </button>
  ) : (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2 py-1 text-[11.5px] text-fg-2 animate-fade-in">{body}</span>
  );
}

export function LiveSteps({ steps, model }: { steps: Step[]; model?: string }) {
  const rows = mergeSteps(steps);
  return (
    <div className="rounded-2xl border border-border bg-surface p-4 shadow-[var(--shadow-card)] animate-fade-in-up">
      <div className="mb-3 flex items-center gap-2 text-[13px] font-medium text-fg-2">
        <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" /><span className="relative inline-flex h-2 w-2 rounded-full bg-primary" /></span>
        Agents at work
        {model && <span className="ml-auto truncate rounded-md bg-surface-2 px-2 py-0.5 text-[11px] font-normal text-muted" title="Model answering this question">{model}</span>}
      </div>
      <ol className="space-y-2.5">
        {rows.map(s => (
          <li key={s.node} className="animate-fade-in">
            <div className="flex items-center gap-2.5 text-[13px]">
              <span className={cn('grid h-5 w-5 shrink-0 place-items-center rounded-full', s.status === 'done' ? 'bg-up/15 text-up' : 'bg-primary/10 text-primary')}>
                {s.status === 'done' ? <Check className="h-3 w-3" strokeWidth={3} /> : <Loader2 className="h-3 w-3 animate-spin" />}
              </span>
              <span className={cn('font-medium', s.status === 'done' ? 'text-fg' : 'text-fg-2')}>{s.label}</span>
              {s.detail && <span className="truncate text-muted">· {s.detail}</span>}
            </div>
            {!!s.tools?.length && (
              <div className="ml-[30px] mt-1.5 flex flex-wrap gap-1.5">{s.tools.map(t => <ToolChip key={t.id} call={t} />)}</div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

export function StepsSummary({ steps, evidence, duration, onOpenTool }:
  { steps: Step[]; evidence?: Evidence[]; duration?: number; onOpenTool?: (evidenceId: string) => void }) {
  const [open, setOpen] = useState(false);
  const rows = mergeSteps(steps);
  if (!rows.length) return null;
  const nTools = rows.reduce((n, s) => n + toolsFor(s, evidence).length, 0);
  return (
    <div className="w-full">
      <button onClick={() => setOpen(o => !o)} aria-expanded={open}
        className="flex items-center gap-1 rounded-md px-1.5 py-1 text-[12px] text-muted transition-colors hover:bg-surface-2 hover:text-fg">
        <ChevronRight className={cn('h-3.5 w-3.5 transition-transform duration-200', open && 'rotate-90')} />
        Agent trace · {rows.length} steps · {nTools} tool calls{duration ? ` · ${duration}s` : ''}
      </button>
      {open && (
        <ol className="ml-2.5 mt-2 space-y-3 border-l border-border pl-4 animate-fade-in">
          {rows.map(s => {
            const tools = toolsFor(s, evidence);
            return (
              <li key={s.node} className="relative">
                <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full border-2 border-surface bg-border-strong" />
                <div className="text-[12.5px]"><span className="font-semibold text-fg">{s.label}</span>{s.detail && <span className="text-muted"> — {s.detail}</span>}</div>
                {tools.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {tools.map(t => <ToolChip key={t.id} call={t} onClick={onOpenTool ? () => onOpenTool(t.id) : undefined} />)}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
