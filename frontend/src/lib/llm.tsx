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
  refresh: () => void;
  loaded: boolean;
}

const LlmCtx = createContext<Ctx>({} as Ctx);
export const useLlm = () => useContext(LlmCtx);
const KEY = 'finsight-llm';

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
    try { sel ? localStorage.setItem(KEY, JSON.stringify(sel)) : localStorage.removeItem(KEY); } catch { /* ignore */ }
  }, []);

  const value = useMemo<Ctx>(() => {
    const providers = data?.providers ?? [];
    // A saved pick is only honoured if that provider still has a key and offers the model.
    const valid = pick && providers.some(p => p.id === pick.provider && p.available && p.models.includes(pick.model));
    const current = valid ? { ...pick!, label: providers.find(p => p.id === pick!.provider)?.label } : data?.default ?? null;
    return {
      providers, serverDefault: data?.default ?? null, source: data?.source ?? '', warnings: data?.warnings ?? [],
      current, isOverride: !!valid, choose, refresh, loaded: !!data,
    };
  }, [data, pick, choose, refresh]);

  return <LlmCtx.Provider value={value}>{children}</LlmCtx.Provider>;
}
