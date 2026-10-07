/* eslint-disable react-refresh/only-export-components -- provider, hook and helpers belong together */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react';

/**
 * Tiny History-API router. Every screen has its own URL, so back/forward, reload, bookmarks
 * and "open in new tab" work:
 *   /                 dashboard          /advisor          new chat
 *   /portfolio        portfolio          /advisor/42       chat #42
 *   /notes /kb /evals /alerts
 */
export type Tab = 'dashboard' | 'portfolio' | 'advisor' | 'notes' | 'kb' | 'evals' | 'alerts';
const TABS: Tab[] = ['dashboard', 'portfolio', 'advisor', 'notes', 'kb', 'evals', 'alerts'];

export interface Route { tab: Tab; chatId: number | null; }

export function parsePath(pathname: string): Route | null {
  const parts = pathname.split('/').filter(Boolean);
  if (parts.length === 0) return { tab: 'dashboard', chatId: null };
  const tab = parts[0] as Tab;
  if (!TABS.includes(tab)) return null;
  if (tab === 'advisor' && parts.length === 2 && /^\d+$/.test(parts[1])) return { tab, chatId: Number(parts[1]) };
  if (parts.length > 1) return null;
  return { tab, chatId: null };
}

export function pathFor(tab: Tab, chatId?: number | null) {
  if (tab === 'dashboard') return '/';
  return tab === 'advisor' && chatId ? `/advisor/${chatId}` : `/${tab}`;
}

interface Ctx extends Route {
  path: string;
  navigate: (path: string, opts?: { replace?: boolean }) => void;
  /** onClick for <a href>: client-side navigation, but ctrl/cmd/middle-click still open a new tab. */
  linkClick: (path: string) => (e: MouseEvent) => void;
}
const RouterCtx = createContext<Ctx>({} as Ctx);
export const useRouter = () => useContext(RouterCtx);

export function RouterProvider({ children }: { children: ReactNode }) {
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const navigate = useCallback((to: string, opts?: { replace?: boolean }) => {
    if (to === window.location.pathname) return;
    if (opts?.replace) window.history.replaceState(null, '', to);
    else window.history.pushState(null, '', to);
    setPath(to);
  }, []);

  // Unknown URLs fall back to the dashboard (replace, so Back doesn't return to them).
  const parsed = parsePath(path);
  // (the dashboard renders straight away; this only fixes the address bar)
  useEffect(() => { if (!parsed) window.history.replaceState(null, '', '/'); }, [parsed]);

  const linkClick = useCallback((to: string) => (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(to);
  }, [navigate]);

  const route = parsed ?? { tab: 'dashboard' as Tab, chatId: null };
  const value = useMemo<Ctx>(() => ({ ...route, path, navigate, linkClick }),
    [route.tab, route.chatId, path, navigate, linkClick]); // eslint-disable-line react-hooks/exhaustive-deps
  return <RouterCtx.Provider value={value}>{children}</RouterCtx.Provider>;
}
