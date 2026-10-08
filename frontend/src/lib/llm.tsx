/* eslint-disable react-refresh/only-export-components -- provider, hook and helpers belong together */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from './api';

export interface LlmProviderInfo {
  id: string; label: string; note: string; models: string[]; default_model: string; available: boolean; keys: number;
}
export interface LlmSelection { provider: string; model: string; label?: string; }
interface ProvidersResponse { providers: LlmProviderInfo[]; default: LlmSelection; source: string; warnings: string[]; }

interface Ctx {
  providers: LlmProviderInfo[];
  serverDefault: LlmSelection | null;
  source: string;
  warnings: string[];
  /** What the next question will use: the user's pick, or the server default. */
  current: LlmSelection | null;
  isOverride: boolean;
  choose: (sel: LlmSelection | null) => void;
  /** Model for one chat: its own pick if it has one, else the default for new chats (`current`). */
  forChat: (chatId: number | null) => { selection: LlmSelection | null; isChatPick: boolean };
  /** Pin a model to one chat (null = follow the default again). */
  chooseForChat: (chatId: number, sel: LlmSelection | null) => void;
  refresh: () => void;
  loaded: boolean;
}

const LlmCtx = createContext<Ctx>({} as Ctx);
export const useLlm = () => useContext(LlmCtx);
const KEY = 'finsight-llm';
const CHAT_KEY = 'finsight-chat-llm'; // { [chatId]: LlmSelection }

/** Short display name: "nvidia/nemotron-3-ultra-550b-a55b:free" -> "nemotron-3-ultra-550b-a55b (free)". */
export function modelName(model?: string | null) {
  if (!model) return '—';
  const base = model.split('/').pop() ?? model;
  return base.endsWith(':free') ? `${base.slice(0, -5)} (free)` : base;
}

export function LlmProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<ProvidersResponse | null>(null);
  const [pick, setPick] = useState<LlmSelection | null>(() => {
    try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; }
  });

  const [chatPicks, setChatPicks] = useState<Record<string, LlmSelection>>(() => {
    try { return JSON.parse(localStorage.getItem(CHAT_KEY) || '{}') ?? {}; } catch { return {}; }
  });

  const refresh = useCallback(() => {
    api<ProvidersResponse>('/agent/providers').then(setData).catch(() => { /* backend offline: keep last */ });
  }, []);
  useEffect(() => {
    refresh();
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    const iv = setInterval(refresh, 60000);
    return () => { window.removeEventListener('focus', onFocus); clearInterval(iv); };
  }, [refresh]);

  const choose = useCallback((sel: LlmSelection | null) => {
    setPick(sel);
    try { if (sel) localStorage.setItem(KEY, JSON.stringify(sel)); else localStorage.removeItem(KEY); } catch { /* ignore */ }
  }, []);

  const chooseForChat = useCallback((chatId: number, sel: LlmSelection | null) => {
    setChatPicks(prev => {
      const next = { ...prev };
      if (sel) next[chatId] = { provider: sel.provider, model: sel.model }; else delete next[chatId];
      try { localStorage.setItem(CHAT_KEY, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  }, []);

  const value = useMemo<Ctx>(() => {
    const providers = data?.providers ?? [];
    // A saved pick is only honoured if that provider still has a key and offers the model.
    const usable = (s?: LlmSelection | null) => !!s && providers.some(p => p.id === s.provider && p.available && p.models.includes(s.model));
    const withLabel = (s: LlmSelection) => ({ ...s, label: providers.find(p => p.id === s.provider)?.label });
    const valid = usable(pick);
    const current = valid ? withLabel(pick!) : data?.default ?? null;
    const forChat = (chatId: number | null) => {
      const own = chatId !== null ? chatPicks[chatId] : null;
      return usable(own) ? { selection: withLabel(own!), isChatPick: true } : { selection: current, isChatPick: false };
    };
    return {
      providers, serverDefault: data?.default ?? null, source: data?.source ?? '', warnings: data?.warnings ?? [],
      current, isOverride: valid, choose, forChat, chooseForChat, refresh, loaded: !!data,
    };
  }, [data, pick, chatPicks, choose, chooseForChat, refresh]);

  return <LlmCtx.Provider value={value}>{children}</LlmCtx.Provider>;
}
