import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Bot, Check, CheckCircle2, ChevronDown, Download, FileCheck2, History, Send, ShieldQuestion, UserRound, X, XCircle } from 'lucide-react';
import { api, API_URL, type AnswerPayload } from '../../lib/api';
import { cn, timeAgo } from '../../lib/format';
import { Badge, Button, Input, Select } from '../ui';
import { useToast } from '../toast';
import DiffView from './DiffView';
import type { ApproveResponse, CorrectResponse, FeedbackItem, ReviewState, ReviewStatus, ReviewedPayload } from './types';

const STATUS: Record<ReviewStatus, { label: string; tone: 'warn' | 'up' | 'down'; icon: typeof CheckCircle2 }> = {
  draft: { label: 'Draft', tone: 'warn', icon: ShieldQuestion },
  approved: { label: 'Approved', tone: 'up', icon: CheckCircle2 },
  rejected: { label: 'Rejected', tone: 'down', icon: XCircle },
};

export function StatusChip({ status }: { status: ReviewStatus }) {
  const s = STATUS[status];
  return <Badge tone={s.tone}><s.icon className="h-3 w-3" />{s.label}</Badge>;
}

const CATEGORY_LABEL: Record<FeedbackItem['category'], string> = { fact: 'Fact', judgement: 'Judgement', weighting: 'Weighting', format: 'Format' };

export interface ReviewBarProps {
  /** Saved chat message id (numeric). Temporary client ids render nothing. */
  messageId: number | string;
  /** The payload currently shown for this message. */
  payload: AnswerPayload;
  /** Called with the payload to display after a correction or when switching versions. */
  onPayloadChange: (payload: AnswerPayload) => void;
  className?: string;
}

/**
 * Expert review strip under an answer: status chip (Draft/Approved/Rejected), version switcher,
 * a correction chat with the Correction Agent (explanations, pushback and diffs), and Approve/Reject.
 */
export default function ReviewBar({ messageId, payload, onPayloadChange, className }: ReviewBarProps) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<ReviewState | null>(null);
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<null | 'correct' | 'approve' | 'reject'>(null);
  const [confirm, setConfirm] = useState<null | 'approve' | 'reject'>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const threadEnd = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const meta = (payload as ReviewedPayload).review;
  const status: ReviewStatus = state?.status ?? meta?.status ?? 'draft';
  const current = state?.current_version ?? meta?.version ?? 1;
  const shown = (payload as ReviewedPayload).review?.shown_version ?? current;
  const id = typeof messageId === 'number' ? messageId : Number.NaN;

  const fetchState = useCallback(() => {
    if (!Number.isFinite(id)) return;
    setLoading(true);
    api<ReviewState>(`/review/${id}`)
      .then(setState)
      .catch(e => toast('error', 'Could not load review', (e as Error).message))
      .finally(() => setLoading(false));
  }, [id, toast]);

  const toggle = () => {
    if (!open && !state && !loading) fetchState();
    setOpen(o => !o);
  };

  useEffect(() => { threadEnd.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }, [state?.feedback.length, busy]);

  if (!Number.isFinite(id) || payload.answer.answer_type === 'general') return null;

  const showVersion = (v: number) => {
    if (!state) return;
    const ver = state.versions.find(x => x.version === v);
    if (!ver) return;
    const base = state.payload;
    onPayloadChange({ ...base, answer: ver.answer, scorecards: ver.scorecards,
      review: { status: state.status, version: state.current_version, approved_version: state.approved_version, shown_version: v } } as ReviewedPayload);
  };

  const apply = (s: ReviewState) => { setState(s); onPayloadChange(s.payload); };

  const send = async (e?: FormEvent, preset?: string) => {
    e?.preventDefault();
    const t = (preset ?? text).trim();
    if (!t || busy) return;
    setBusy('correct');
    try {
      const r = await api<CorrectResponse>(`/review/${id}/correct`, { method: 'POST', body: JSON.stringify({ text: t }) });
      setText('');
      apply(r.review);
      setExpanded(r.feedback.id);
      if (r.new_version) toast('success', `Updated to v${r.new_version}`, r.agent_response);
      else if (!r.accepted) toast('info', 'The agent pushed back', r.pushback ?? undefined);
    } catch (err) {
      toast('error', 'Correction failed', (err as Error).message);
    } finally {
      setBusy(null);
      inputRef.current?.focus();
    }
  };

  const approve = async () => {
    setBusy('approve'); setConfirm(null);
    try {
      const r = await api<ApproveResponse>(`/review/${id}/approve`, { method: 'POST', body: JSON.stringify({ version: shown }) });
      apply(r.review);
      if (r.publish.status === 'published') toast('success', `v${r.note.version} approved and published`, r.publish.idempotent ? 'It was already published - nothing was sent twice.' : 'Pushed to Research Notes.');
      else toast('error', `v${r.note.version} approved, publishing failed`, r.publish.error);
    } catch (err) {
      toast('error', 'Approve failed', (err as Error).message);
    } finally { setBusy(null); }
  };

  const reject = async () => {
    setBusy('reject'); setConfirm(null);
    try {
      apply(await api<ReviewState>(`/review/${id}/reject`, { method: 'POST', body: JSON.stringify({}) }));
      toast('info', 'Answer rejected', 'It will not be published unless corrected and approved.');
    } catch (err) {
      toast('error', 'Reject failed', (err as Error).message);
    } finally { setBusy(null); }
  };

  const factorNames = new Set((payload.scorecards ?? []).flatMap(c => c.factors.map(f => f.name)));
  const suggestions = [
    factorNames.has('xgboost') && 'Ignore the XGBoost signal',
    factorNames.has('valuation') && 'Weight valuation higher',
    factorNames.has('momentum') && 'Halve the momentum weight',
  ].filter(Boolean) as string[];

  return (
    <div className={cn('mt-4 rounded-xl border border-border bg-surface-2/60', className)}>
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <StatusChip status={status} />
        <span className="text-[12px] text-muted tabular">
          v{shown}{shown !== current && <> of v{current}</>}
          {state?.approved_version && <> · approved v{state.approved_version}</>}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {open && state && (
            <>
              {state.versions.length > 1 && (
                <Select aria-label="Version" value={shown} onChange={e => showVersion(Number(e.target.value))} className="h-8 w-auto py-0 text-[12.5px]">
                  {state.versions.map(v => <option key={v.version} value={v.version}>v{v.version} · {v.author === 'agent' ? 'agent' : 'analyst'}</option>)}
                </Select>
              )}
              <Button size="sm" variant="outline" onClick={() => setConfirm('reject')} disabled={!!busy || status === 'rejected'}
                className="hover:border-down/40 hover:text-down"><X className="h-3.5 w-3.5" />Reject</Button>
              <Button size="sm" onClick={() => setConfirm('approve')} loading={busy === 'approve'} disabled={!!busy}>
                <Check className="h-3.5 w-3.5" />Approve v{shown}
              </Button>
            </>
          )}
          <Button size="sm" variant="ghost" onClick={toggle} aria-expanded={open}>
            <History className="h-3.5 w-3.5" />{open ? 'Close' : 'Review'}
            <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
          </Button>
        </div>
      </div>

      {confirm && (
        <div className="mx-3 mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-[13px] animate-fade-in">
          <span className="text-fg-2">
            {confirm === 'approve'
              ? <>Approve <b className="text-fg">v{shown}</b> and publish it to Research Notes?</>
              : <>Reject this answer? It stays unpublished until corrected and approved.</>}
          </span>
          <span className="ml-auto flex gap-1.5">
            <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
            <Button size="sm" variant={confirm === 'approve' ? 'primary' : 'danger'} onClick={confirm === 'approve' ? approve : reject}>
              {confirm === 'approve' ? 'Approve & publish' : 'Reject'}
            </Button>
          </span>
        </div>
      )}

      {open && (
        <div className="border-t border-border px-3 pb-3 pt-2.5 animate-fade-in">
          {loading && !state ? <p className="py-3 text-[13px] text-muted">Loading review…</p> : state && (
            <div className="space-y-3">
              {state.feedback.length === 0 && (
                <p className="text-[13px] text-muted">
                  Tell the agent what to fix in plain English. It checks your note against the evidence, updates the answer as a new
                  version and explains the change - or pushes back if the data says otherwise. Every note is logged as training data.
                </p>
              )}
              {state.feedback.map(f => {
                const from = state.versions.find(v => v.version === f.from_version);
                const to = state.versions.find(v => v.version === f.to_version);
                const isOpen = expanded === f.id;
                return (
                  <div key={f.id} className="space-y-1.5">
                    <div className="flex justify-end gap-2">
                      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary/10 px-3 py-2 text-[13.5px] text-fg">{f.correction_text}</div>
                      <span className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-surface-3 text-muted"><UserRound className="h-3.5 w-3.5" /></span>
                    </div>
                    <div className="flex gap-2">
                      <span className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-primary/10 text-primary"><Bot className="h-3.5 w-3.5" /></span>
                      <div className="min-w-0 flex-1 space-y-1.5">
                        <div className={cn('rounded-2xl rounded-bl-md border px-3 py-2 text-[13.5px]',
                          f.accepted ? 'border-border bg-surface text-fg-2' : 'border-warn/25 bg-warn/[0.07] text-fg-2')}>
                          <div className="mb-1 flex flex-wrap items-center gap-1.5">
                            <Badge tone={f.accepted ? (f.to_version ? 'up' : 'neutral') : 'warn'}>
                              {f.accepted ? (f.to_version ? `Applied → v${f.to_version}` : 'No change') : 'Pushback'}
                            </Badge>
                            <Badge>{CATEGORY_LABEL[f.category]}</Badge>
                            <span className="text-[11px] text-muted">{timeAgo(f.created_at)}</span>
                          </div>
                          {f.agent_response}
                        </div>
                        {from && to && (
                          <button onClick={() => setExpanded(isOpen ? null : f.id)} className="inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline">
                            {isOpen ? 'Hide changes' : `Show changes v${from.version} → v${to.version}`}
                            <ChevronDown className={cn('h-3 w-3 transition-transform', isOpen && 'rotate-180')} />
                          </button>
                        )}
                        {isOpen && from && to && (
                          <DiffView before={from.answer} after={to.answer} beforeCards={from.scorecards} afterCards={to.scorecards}
                            changeLog={f.change_log} fromVersion={from.version} toVersion={to.version} className="animate-fade-in" />
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
              {busy === 'correct' && <p className="pl-8 text-[12.5px] text-muted animate-pulse">Correction Agent is checking the evidence…</p>}
              <div ref={threadEnd} />

              {suggestions.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {suggestions.map(s => (
                    <button key={s} onClick={() => send(undefined, s)} disabled={!!busy}
                      className="rounded-full border border-border bg-surface px-2.5 py-1 text-[12px] text-fg-2 transition-colors hover:border-border-strong hover:text-fg disabled:opacity-50">{s}</button>
                  ))}
                </div>
              )}
              <form onSubmit={send} className="flex gap-2">
                <Input ref={inputRef} value={text} onChange={e => setText(e.target.value)} disabled={busy === 'correct'} maxLength={2000}
                  placeholder='Correct the answer, e.g. "Ignore the XGBoost signal" or "RSI should be 45"' aria-label="Correction" />
                <Button type="submit" loading={busy === 'correct'} disabled={!text.trim()}><Send className="h-3.5 w-3.5" />Send</Button>
              </form>
              <div className="flex flex-wrap items-center gap-3 text-[12px] text-muted">
                {state.notes.filter(n => n.connector_status === 'published').map(n => (
                  <span key={n.id} className="inline-flex items-center gap-1 text-up"><FileCheck2 className="h-3.5 w-3.5" />v{n.version} published · note #{n.id}</span>
                ))}
                <a href={`${API_URL}/review/feedback/export.jsonl`} className="ml-auto inline-flex items-center gap-1 transition-colors hover:text-fg">
                  <Download className="h-3.5 w-3.5" />Feedback (JSONL)
                </a>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
