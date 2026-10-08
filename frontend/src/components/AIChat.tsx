import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowUp, Briefcase, Loader2, Lightbulb, LineChart, MessageSquare, PanelLeft, Plus, Scale, Sparkles, Trash2, TriangleAlert } from 'lucide-react';
import { api, type ChatMessage, type ChatSummary } from '../lib/api';
import { cn } from '../lib/format';
import { useToast } from './toast';
import { Button, Skeleton } from './ui';
import AnswerView from './advisor/AnswerView';
import EvidencePanel from './advisor/EvidencePanel';
import { LiveSteps } from './advisor/AgentSteps';
import ResizeHandle from './ResizeHandle';
import ModelPicker from './ModelPicker';
import { modelName, useLlm } from '../lib/llm';
import { useRouter } from '../lib/router';
import { useAdvisorRuns } from '../lib/advisorRuns';
import ReviewBar from './review/ReviewBar';
import { InspectNotice, useInspectMode } from '../lib/appConfig';

const SUGGESTIONS = [
  { icon: Briefcase, title: 'Check my portfolio health', prompt: 'Check the health of my portfolio' },
  { icon: LineChart, title: 'Analyse a stock', prompt: 'How is Tech Mahindra looking right now?' },
  { icon: Scale, title: 'Compare two stocks', prompt: 'Compare TCS and Infosys' },
  { icon: Lightbulb, title: 'Find new ideas', prompt: 'What should I add to my portfolio?' },
];

function groupChats(chats: ChatSummary[]) {
  const now = new Date(); const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups: { label: string; items: ChatSummary[] }[] = [
    { label: 'Today', items: [] }, { label: 'Yesterday', items: [] }, { label: 'Previous 7 days', items: [] }, { label: 'Older', items: [] }];
  for (const c of chats) {
    const raw = c.updated_at ?? c.created_at ?? '';
    const t = new Date(raw.endsWith('Z') || raw.includes('+') ? raw : `${raw}Z`).getTime();
    const idx = t >= startToday ? 0 : t >= startToday - 864e5 ? 1 : t >= startToday - 7 * 864e5 ? 2 : 3;
    groups[idx].items.push(c);
  }
  return groups.filter(g => g.items.length);
}

export default function Advisor() {
  const toast = useToast();
  const inspect = useInspectMode();
  const { chatId: activeId, navigate, linkClick } = useRouter();   // the open chat comes from the URL
  const runsCtx = useAdvisorRuns();
  const llmCtx = useLlm();
  const llm = llmCtx.forChat(activeId).selection; // each chat keeps its own model
  const [chats, setChats] = useState<ChatSummary[] | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingChat, setLoadingChat] = useState(false);
  const [newRunKey, setNewRunKey] = useState<string | null>(null); // run started from the "New chat" screen
  const [input, setInput] = useState('');
  const [drawer, setDrawer] = useState<{ messageId: ChatMessage['id']; evidenceId: string | null } | null>(null);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [historyWidth, setHistoryWidth] = usePersistentWidth('finsight-history-w', 264);
  const [drawerWidth, setDrawerWidth] = usePersistentWidth('finsight-sources-w', 440);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const activeRef = useRef<number | null>(activeId); // read by async callbacks: which chat is open *now*
  useLayoutEffect(() => { activeRef.current = activeId; }, [activeId]);
  const adoptRef = useRef<number | null>(null); // chat we just created ourselves: keep the on-screen messages

  // The run shown in this thread: the chat's own run, or the one started from "New chat".
  const pending = activeId !== null
    ? runsCtx.runForChat(activeId)
    : runsCtx.runs.find(r => r.key === newRunKey && r.sessionId === null);

  const scrollToBottom = (smooth = true) =>
    requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: smooth ? 'smooth' : 'auto' }));

  const openDrawer = (messageId: ChatMessage['id'], evidenceId: string | null) => {
    setDrawer({ messageId, evidenceId });
    if (window.innerWidth - drawerWidth - historyWidth < 720) setHistoryOpen(false); // keep the thread readable
  };

  const loadChats = useCallback(() => api<ChatSummary[]>('/chats').then(setChats).catch(() => setChats([])), []);
  useEffect(() => { loadChats(); }, [loadChats, runsCtx.chatsVersion]);

  const loadMessages = useCallback(async (id: number, quiet = false) => {
    if (!quiet) setLoadingChat(true);
    try {
      const data = await api<{ messages: ChatMessage[] }>(`/chats/${id}`);
      if (activeRef.current === id) setMessages(data.messages);
    } catch (e) {
      if (activeRef.current === id) {
        toast('error', 'Could not open chat', (e as Error).message);
        navigate('/advisor', { replace: true });
      }
    } finally { if (!quiet) setLoadingChat(false); }
  }, [navigate, toast]);

  // Load whichever chat the URL points at (also on back/forward and reload).
  useEffect(() => {
    // Syncing with the URL (an external system), so resetting state here is intended.
    setDrawer(null); // eslint-disable-line react-hooks/set-state-in-effect
    if (activeId === null) { setMessages([]); setLoadingChat(false); return; }
    if (adoptRef.current === activeId) { adoptRef.current = null; return; }
    loadMessages(activeId);
  }, [activeId, loadMessages]);

  // A run started from "New chat" got its chat id: move the URL to that chat (same history entry).
  useEffect(() => {
    if (!newRunKey) return;
    const run = runsCtx.runs.find(r => r.key === newRunKey);
    if (run?.sessionId != null) {
      setNewRunKey(null); // eslint-disable-line react-hooks/set-state-in-effect
      if (run.llm) llmCtx.chooseForChat(run.sessionId, run.llm); // the new chat keeps the model it started with
      if (activeRef.current === null) { adoptRef.current = run.sessionId; navigate(`/advisor/${run.sessionId}`, { replace: true }); }
    } else if (!run) setNewRunKey(null);
  }, [runsCtx.runs, newRunKey, navigate]); // eslint-disable-line react-hooks/exhaustive-deps

  // An answer was saved: refresh the open chat from the server.
  useEffect(() => {
    const f = runsCtx.lastFinished;
    if (f && f.sessionId === activeRef.current) { loadMessages(f.sessionId, true); scrollToBottom(); }
  }, [runsCtx.lastFinished]); // eslint-disable-line react-hooks/exhaustive-deps

  const newChat = () => { navigate('/advisor'); setTimeout(() => inputRef.current?.focus(), 0); };

  const deleteChat = async (id: number) => {
    try {
      await api(`/chats/${id}`, { method: 'DELETE' });
      setChats(c => c?.filter(x => x.id !== id) ?? c);
      if (id === activeId) navigate('/advisor', { replace: true });
      toast('success', 'Chat deleted');
    } catch (e) { toast('error', 'Could not delete chat', (e as Error).message); }
  };

  useEffect(() => { scrollToBottom(false); }, [activeId, loadingChat]);
  useEffect(() => { if (pending) scrollToBottom(); }, [pending?.steps.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = (text?: string) => {
    const question = (text ?? input).trim();
    if (!question || (pending && pending.status === 'running') || inspect) return;
    if (pending) runsCtx.dismiss(pending.key); // clear a previous error
    setInput('');
    setMessages(m => [...m, { id: `u-${Date.now()}`, role: 'user', content: question }]);
    const key = runsCtx.start(question, activeId, llm);
    if (activeId === null) setNewRunKey(key);
    scrollToBottom();
  };

  const retry = () => {
    if (!pending) return;
    const q = pending.question;
    setMessages(m => (m.length && m[m.length - 1].role === 'user' ? m.slice(0, -1) : m));
    runsCtx.dismiss(pending.key);
    setTimeout(() => send(q), 0);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
  };

  useEffect(() => {
    const el = inputRef.current; if (!el) return;
    el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const drawerMessage = useMemo(() => drawer && messages.find(m => m.id === drawer.messageId && m.payload), [drawer, messages]);
  const showPending = !!pending;
  const empty = !loadingChat && messages.length === 0 && !showPending;
  const grouped = groupChats(chats ?? []);
  // Sources panel may never squeeze the thread below 440px (232px = app sidebar).
  const drawerMax = Math.max(340, window.innerWidth - 232 - (historyOpen ? historyWidth : 0) - 440);

  return (
    <div className="flex h-full">
      {/* History */}
      <aside style={{ width: historyOpen ? historyWidth : 0 }}
        className={cn('flex shrink-0 flex-col bg-surface', historyOpen ? 'opacity-100' : 'overflow-hidden opacity-0')}>
        <div className="flex h-14 shrink-0 items-center gap-2 px-3">
          <Button onClick={newChat} variant="outline" className="flex-1 justify-start"><Plus className="h-4 w-4" />New chat</Button>
        </div>
        <div className="flex-1 overflow-y-auto px-2 pb-3">
          {chats === null ? <div className="space-y-2 p-1">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-8" />)}</div> : chats.length === 0 ? (
            <p className="px-3 py-6 text-center text-[13px] text-muted">Your conversations will appear here.</p>
          ) : grouped.map(g => (
            <div key={g.label} className="mt-3 first:mt-1">
              <div className="px-2.5 pb-1 text-[11px] font-medium text-muted">{g.label}</div>
              {g.items.map(c => (
                <div key={c.id}
                  className={cn('group flex items-center rounded-lg transition-colors', c.id === activeId ? 'bg-surface-2 text-fg' : 'text-fg-2 hover:bg-surface-2/70 hover:text-fg')}>
                  <a href={`/advisor/${c.id}`} onClick={linkClick(`/advisor/${c.id}`)} aria-current={c.id === activeId ? 'page' : undefined}
                    className="flex min-w-0 flex-1 items-center gap-2 px-2.5 py-2 text-left text-[13px]">
                    {runsCtx.runForChat(c.id)?.status === 'running'
                      ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" aria-label="Agents working" />
                      : <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" />}
                    <span className="truncate">{c.title}</span>
                  </a>
                  {!inspect && <button onClick={() => deleteChat(c.id)} aria-label="Delete chat"
                    className="mr-1 rounded-md p-1.5 text-muted opacity-0 transition-all hover:bg-down/10 hover:text-down group-hover:opacity-100 focus:opacity-100">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>}
                </div>
              ))}
            </div>
          ))}
        </div>
      </aside>
      {historyOpen ? (
        <ResizeHandle label="Resize chat list" side="left" width={historyWidth} onChange={setHistoryWidth} min={200} max={420} onReset={() => setHistoryWidth(264)} />
      ) : <div className="w-px shrink-0 bg-border" />}

      {/* Thread */}
      <section className="@container flex min-w-[440px] flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
          <Button variant="ghost" size="icon" onClick={() => setHistoryOpen(o => !o)} aria-label="Toggle chat history"><PanelLeft className="h-[18px] w-[18px]" /></Button>
          <div className="min-w-0 truncate text-sm font-medium">{chats?.find(c => c.id === activeId)?.title ?? 'New chat'}</div>
          <div className="ml-auto shrink-0"><ModelPicker align="right" chatId={activeId} /></div>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-5 py-8">
            {loadingChat && <div className="space-y-4"><Skeleton className="ml-auto h-10 w-1/2" /><Skeleton className="h-40" /></div>}

            {empty && (
              <div className="pt-[8vh] text-center animate-fade-in-up">
                <div className="mx-auto mb-5 grid h-12 w-12 place-items-center rounded-2xl bg-primary/10 text-primary"><Sparkles className="h-6 w-6" /></div>
                <h2 className="text-2xl font-semibold tracking-tight">What would you like to research?</h2>
                <p className="mx-auto mt-2 max-w-md text-sm text-muted">Research, Sentiment and Risk agents gather live data, a Synthesis agent writes the answer, and a Validation agent checks every claim against its source.</p>
                {inspect ? (
                  <InspectNotice className="mx-auto mt-8 max-w-xl">
                    To save LLM credits, new questions can't be sent on this public deployment. Open a saved conversation from the list on the left to see a full multi-agent answer, its agent trace and every cited source.
                  </InspectNotice>
                ) : (
                <div className="mx-auto mt-8 grid max-w-xl gap-2.5 sm:grid-cols-2">
                  {SUGGESTIONS.map(s => (
                    <button key={s.title} onClick={() => send(s.prompt)}
                      className="group flex items-start gap-3 rounded-xl border border-border bg-surface p-3.5 text-left transition-all duration-150 hover:-translate-y-0.5 hover:border-border-strong hover:shadow-[var(--shadow-pop)] active:translate-y-0">
                      <s.icon className="mt-0.5 h-4 w-4 text-muted transition-colors group-hover:text-primary" />
                      <span><span className="block text-sm font-medium">{s.title}</span><span className="block text-[12px] text-muted">{s.prompt}</span></span>
                    </button>
                  ))}
                </div>
                )}
              </div>
            )}

            <div className="space-y-8">
              {!loadingChat && messages.map(m => m.role === 'user' ? (
                <div key={m.id} className="flex justify-end animate-fade-in-up">
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[14.5px] text-primary-fg">{m.content}</div>
                </div>
              ) : (
                <div key={m.id} className="flex gap-3 animate-fade-in-up">
                  <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"><Sparkles className="h-3.5 w-3.5" /></div>
                  <div className="min-w-0 flex-1">
                    {m.payload ? (
                      <AnswerView payload={m.payload}
                        activeCitation={drawer?.messageId === m.id ? drawer.evidenceId : null}
                        onCite={id => openDrawer(m.id, id)}
                        onOpenSources={() => openDrawer(m.id, null)} />
                    ) : <p className="text-[15px] text-fg-2">{m.content}</p>}
                    {m.payload && (
                      <ReviewBar messageId={m.id} payload={m.payload}
                        onPayloadChange={p => setMessages(ms => ms.map(x => (x.id === m.id ? { ...x, payload: p } : x)))} />
                    )}
                  </div>
                </div>
              ))}

              {showPending && pending && (
                <div className="flex gap-3">
                  <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"><Sparkles className="h-3.5 w-3.5" /></div>
                  <div className="min-w-0 flex-1">
                    {pending.status === 'error' ? (
                      <div className="rounded-2xl border border-down/25 bg-down/[0.06] p-4 animate-fade-in">
                        <div className="flex items-center gap-2 text-sm font-medium text-down"><TriangleAlert className="h-4 w-4" />The agents hit a problem</div>
                        <p className="mt-1 break-words text-[13px] text-fg-2">{pending.error}</p>
                        {pending.llm && <p className="mt-2 text-[12px] text-muted">Model: <span className="font-medium text-fg-2">{pending.llm.label ?? pending.llm.provider} · {modelName(pending.llm.model)}</span>
                          {/overload|\b(429|402)\b|rate.?limit|quota|insufficient credit|out of credit/i.test(pending.error ?? "") && ' — this provider is busy or out of quota; pick another model in the top-right and try again.'}</p>}
                        <Button size="sm" variant="outline" className="mt-3" onClick={retry}>Try again</Button>
                      </div>
                    ) : <LiveSteps model={pending.llm ? `${pending.llm.label ?? pending.llm.provider} · ${modelName(pending.llm.model)}` : undefined}
                          steps={pending.steps.length ? pending.steps : [{ node: 'orchestrator_node', label: 'Orchestrator', status: 'running', detail: 'Understanding your question' }]} />}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Composer */}
        <div className="shrink-0 px-5 pb-5">
          <div className="mx-auto max-w-3xl">
            {inspect ? (!empty && <InspectNotice />) : (<>
            <div className={cn('flex items-end gap-2 rounded-2xl border bg-surface p-2 pl-4 shadow-[var(--shadow-card)] transition-[border-color,box-shadow] duration-150',
              'border-border focus-within:border-primary focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--primary)_14%,transparent)]')}>
              <textarea ref={inputRef} rows={1} value={input} onChange={e => setInput(e.target.value)} onKeyDown={onKeyDown}
                placeholder="Ask about a stock, your portfolio, or new ideas…"
                className="max-h-[200px] flex-1 resize-none bg-transparent py-2 text-[14.5px] text-fg placeholder:text-muted focus:outline-none" />
              <Button size="icon" onClick={() => send()} disabled={!input.trim() || pending?.status === 'running'} aria-label="Send" className="rounded-xl">
                <ArrowUp className="h-4 w-4" />
              </Button>
            </div>
            <p className="mt-2 text-center text-[11px] text-muted">Paper-trading research tool. Not investment advice. Enter to send · Shift+Enter for a new line</p>
            </>)}
          </div>
        </div>
      </section>

      {/* Sources drawer */}
      {drawer && drawerMessage?.payload && (
        <>
          <ResizeHandle label="Resize sources panel" side="right" width={drawerWidth} onChange={setDrawerWidth}
            min={340} max={drawerMax} onReset={() => setDrawerWidth(440)} />
          <div style={{ width: Math.min(drawerWidth, drawerMax) }} className="h-full shrink-0">
            <EvidencePanel payload={drawerMessage.payload} activeId={drawer.evidenceId} onClose={() => setDrawer(null)} />
          </div>
        </>
      )}
    </div>
  );
}

/** Panel width remembered across reloads (falls back silently if storage is unavailable). */
function usePersistentWidth(key: string, initial: number) {
  const [w, setW] = useState<number>(() => {
    try { const v = Number(localStorage.getItem(key)); return v > 0 ? v : initial; } catch { return initial; }
  });
  const set = useCallback((v: number) => {
    setW(v);
    try { localStorage.setItem(key, String(v)); } catch { /* ignore */ }
  }, [key]);
  return [w, set] as const;
}
