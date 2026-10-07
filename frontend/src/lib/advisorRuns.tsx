/* eslint-disable react-refresh/only-export-components -- provider, hook and helpers belong together */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, API_URL, type Step } from './api';
import type { LlmSelection } from './llm';

/**
 * Agent runs live here, above the pages, so they keep streaming while the user is on another
 * screen. The backend runs the agents independently of the connection, so after a reload (or a
 * dropped connection) we re-attach to the run and replay its progress.
 */
export interface Run {
  key: string;
  sessionId: number | null;
  question: string;
  steps: Step[];
  llm?: LlmSelection | null;
  status: 'running' | 'error';
  error?: string;
  lastSeq: number;
}
export interface Finished { key: string; sessionId: number; messageId: number; question: string; at: number; }

interface Ctx {
  runs: Run[];
  /** Start a question; resolves to the run key (the chat id arrives later via the run). */
  start: (question: string, sessionId: number | null, llm: LlmSelection | null) => string;
  dismiss: (key: string) => void;
  runForChat: (chatId: number | null) => Run | undefined;
  /** Bumped when the chat list should reload (new chat created / answer saved). */
  chatsVersion: number;
  lastFinished: Finished | null;
}

const RunsCtx = createContext<Ctx>({} as Ctx);
export const useAdvisorRuns = () => useContext(RunsCtx);

interface RunEvent { type: string; seq?: number; session_id?: number; llm?: LlmSelection; message_id?: number; content?: string; [k: string]: unknown; }

export function AdvisorRunsProvider({ children }: { children: ReactNode }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [chatsVersion, setChatsVersion] = useState(0);
  const [lastFinished, setLastFinished] = useState<Finished | null>(null);
  const attached = useRef(new Set<number>()); // chat ids with a live connection (StrictMode-safe)
  const runsRef = useRef(runs);
  runsRef.current = runs;

  const patch = useCallback((key: string, f: (r: Run) => Run | null) =>
    setRuns(rs => rs.flatMap(r => {
      if (r.key !== key) return [r];
      const next = f(r);
      return next ? [next] : [];
    })), []);

  /** Read an SSE response until the run ends. Returns 'ended' or 'dropped' (connection lost mid-run). */
  const consume = useCallback(async (key: string, res: Response, question: string): Promise<'ended' | 'dropped'> => {
    if (!res.ok || !res.body) {
      let msg = `Server returned ${res.status}`;
      try { const b = await res.json(); if (b?.detail) msg = String(b.detail); } catch { /* not JSON */ }
      throw new Error(msg);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let sessionId: number | null = runsRef.current.find(r => r.key === key)?.sessionId ?? null;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop() ?? '';
        for (const raw of chunks) {
          const line = raw.split('\n').find(l => l.startsWith('data: '));
          if (!line) continue;
          const ev = JSON.parse(line.slice(6)) as RunEvent;
          const seq = typeof ev.seq === 'number' ? ev.seq : undefined;
          const bump = (r: Run) => (seq === undefined ? r : { ...r, lastSeq: Math.max(r.lastSeq, seq) });
          if (ev.type === 'session') {
            sessionId = ev.session_id ?? null;
            if (sessionId !== null) attached.current.add(sessionId);
            patch(key, r => bump({ ...r, sessionId, llm: ev.llm ?? r.llm }));
            setChatsVersion(v => v + 1);
          } else if (ev.type === 'step') {
            patch(key, r => bump({ ...r, steps: [...r.steps, ev as unknown as Step] }));
          } else if (ev.type === 'final') {
            patch(key, () => null);
            if (sessionId !== null) {
              attached.current.delete(sessionId);
              setLastFinished({ key, sessionId, messageId: Number(ev.message_id), question, at: Date.now() });
            }
            setChatsVersion(v => v + 1);
            return 'ended';
          } else if (ev.type === 'error') {
            if (sessionId !== null) attached.current.delete(sessionId);
            patch(key, r => bump({ ...r, status: 'error', error: ev.content ?? 'Something went wrong' }));
            return 'ended';
          }
        }
      }
    } catch {
      return 'dropped';
    }
    return 'dropped';
  }, [patch]);

  /** Follow an existing run on the server, re-attaching if the connection drops. */
  const follow = useCallback(async (key: string, chatId: number, question: string) => {
    for (let attempt = 0; attempt < 6; attempt++) {
      const after = (runsRef.current.find(r => r.key === key)?.lastSeq ?? -1) + 1;
      try {
        const res = await fetch(`${API_URL}/agent/runs/${chatId}/events?after=${after}`);
        if (res.status === 404) { // finished long ago (or the server restarted): the chat has whatever was saved
          attached.current.delete(chatId);
          patch(key, () => null);
          setChatsVersion(v => v + 1);
          setLastFinished({ key, sessionId: chatId, messageId: -1, question, at: Date.now() });
          return;
        }
        if ((await consume(key, res, question)) === 'ended') return;
      } catch { /* network error: retry below */ }
      await new Promise(r => setTimeout(r, Math.min(8000, 1000 * 2 ** attempt)));
    }
    attached.current.delete(chatId);
    patch(key, r => ({ ...r, status: 'error', error: 'Lost the connection to the server. The answer will appear in this chat if the agents finish.' }));
  }, [consume, patch]);

  const start = useCallback((question: string, sessionId: number | null, llm: LlmSelection | null) => {
    const key = `run-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setRuns(rs => [...rs, { key, sessionId, question, steps: [], llm, status: 'running', lastSeq: -1 }]);
    if (sessionId !== null) attached.current.add(sessionId);
    (async () => {
      let outcome: 'ended' | 'dropped';
      try {
        const res = await fetch(`${API_URL}/agent/chat`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: question, session_id: sessionId, provider: llm?.provider, model: llm?.model }),
        });
        outcome = await consume(key, res, question);
      } catch (e) {
        if (sessionId !== null) attached.current.delete(sessionId);
        patch(key, r => ({ ...r, status: 'error', error: (e as Error).message }));
        return;
      }
      if (outcome === 'dropped') {
        const chatId = runsRef.current.find(r => r.key === key)?.sessionId;
        if (chatId) follow(key, chatId, question);
        else patch(key, r => ({ ...r, status: 'error', error: 'Lost the connection to the server.' }));
      }
    })();
    return key;
  }, [consume, follow, patch]);

  // After a reload: pick up runs that are still going on the server.
  useEffect(() => {
    let cancelled = false;
    api<{ chat_id: number; question: string; llm: LlmSelection; status: string }[]>('/agent/runs').then(list => {
      if (cancelled) return;
      for (const r of list) {
        if (r.status !== 'running' || attached.current.has(r.chat_id)) continue;
        attached.current.add(r.chat_id);
        const key = `resume-${r.chat_id}`;
        setRuns(rs => [...rs, { key, sessionId: r.chat_id, question: r.question, steps: [], llm: r.llm, status: 'running', lastSeq: -1 }]);
        follow(key, r.chat_id, r.question);
      }
    }).catch(() => { /* backend offline */ });
    return () => { cancelled = true; };
  }, [follow]);

  const dismiss = useCallback((key: string) => patch(key, () => null), [patch]);
  const runForChat = useCallback((chatId: number | null) => runs.find(r => r.sessionId === chatId), [runs]);

  const value = useMemo(() => ({ runs, start, dismiss, runForChat, chatsVersion, lastFinished }),
    [runs, start, dismiss, runForChat, chatsVersion, lastFinished]);
  return <RunsCtx.Provider value={value}>{children}</RunsCtx.Provider>;
}
