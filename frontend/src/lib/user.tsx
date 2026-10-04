import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { api, WS_URL, type User } from './api';

interface Ctx {
  user: User | null; loading: boolean; error: string | null; reload: () => void;
  livePrices: Record<string, number>; wsConnected: boolean; unreadAlerts: number; refreshUnread: () => void;
}
const UserCtx = createContext<Ctx>({} as Ctx);
export const useApp = () => useContext(UserCtx);

/** Loads the single demo user and keeps one shared WebSocket for prices, alerts and balance. */
export function AppDataProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [wsConnected, setWsConnected] = useState(false);
  const [unreadAlerts, setUnread] = useState(0);
  const retry = useRef(0);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    api<User>('/me').then(setUser).catch(e => setError(String(e.message ?? e))).finally(() => setLoading(false));
  }, []);

  const refreshUnread = useCallback(() => {
    api<{ count: number }>('/alerts/unread-count').then(d => setUnread(d.count)).catch(() => {});
  }, []);

  useEffect(reload, [reload]);

  useEffect(() => {
    if (!user) return;
    refreshUnread();
    const iv = setInterval(refreshUnread, 30000);
    let ws: WebSocket | null = null;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(`${WS_URL}/ws/${user.id}`);
      ws.onopen = () => { setWsConnected(true); retry.current = 0; };
      ws.onclose = () => {
        setWsConnected(false);
        if (!closed) setTimeout(connect, Math.min(15000, 1000 * 2 ** retry.current++));
      };
      ws.onmessage = ev => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.event === 'price_update') setLivePrices(p => ({ ...p, [msg.data.ticker]: msg.data.price }));
          if (msg.event === 'alert') {
            if (msg.data.type === 'balance_update') setUser(u => (u ? { ...u, balance: msg.data.balance } : u));
            else refreshUnread();
          }
        } catch { /* ignore malformed */ }
      };
    };
    connect();
    return () => { closed = true; clearInterval(iv); ws?.close(); };
  }, [user?.id, refreshUnread]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <UserCtx.Provider value={{ user, loading, error, reload, livePrices, wsConnected, unreadAlerts, refreshUnread }}>
      {children}
    </UserCtx.Provider>
  );
}
