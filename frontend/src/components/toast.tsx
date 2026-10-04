import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { CheckCircle2, Info, X, XCircle } from 'lucide-react';
import { cn } from '../lib/format';

type Kind = 'success' | 'error' | 'info';
interface Toast { id: number; kind: Kind; title: string; body?: string; }

const ToastCtx = createContext<(kind: Kind, title: string, body?: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = (id: number) => setToasts(t => t.filter(x => x.id !== id));
  const push = useCallback((kind: Kind, title: string, body?: string) => {
    const id = Date.now() + Math.random();
    setToasts(t => [...t.slice(-3), { id, kind, title, body }]);
    setTimeout(() => dismiss(id), 4000);
  }, []);

  const icon = { success: <CheckCircle2 className="h-4 w-4 text-up" />, error: <XCircle className="h-4 w-4 text-down" />, info: <Info className="h-4 w-4 text-primary" /> };

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[340px] max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {toasts.map(t => (
          <div key={t.id} className={cn('pointer-events-auto flex items-start gap-3 rounded-xl border border-border bg-surface p-3.5 shadow-[var(--shadow-pop)] animate-fade-in-up')}>
            <div className="mt-0.5">{icon[t.kind]}</div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-fg">{t.title}</p>
              {t.body && <p className="mt-0.5 text-[13px] text-muted break-words">{t.body}</p>}
            </div>
            <button onClick={() => dismiss(t.id)} className="rounded-md p-0.5 text-muted transition-colors hover:bg-surface-2 hover:text-fg" aria-label="Dismiss">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
