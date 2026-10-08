import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { Eye, Mail } from 'lucide-react';
import { api } from './api';
import { cn } from './format';

/** Site mode set on the server (APP_MODE in .env). Inspect = browse only, no LLM calls. */
export interface AppConfig { mode: 'demo' | 'inspect'; contact_email: string; message: string | null; }

const DEFAULT: AppConfig = { mode: 'demo', contact_email: '', message: null };
const ConfigCtx = createContext<AppConfig>(DEFAULT);
export const useAppConfig = () => useContext(ConfigCtx);
export const useInspectMode = () => useContext(ConfigCtx).mode === 'inspect';

export function AppConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig>(DEFAULT);
  useEffect(() => {
    // Retry until the backend answers: if the first request lands while the backend is restarting
    // (e.g. right after a deploy), giving up would silently show demo mode and hide the inspect banner.
    let cancelled = false, timer: ReturnType<typeof setTimeout> | undefined, delay = 2000;
    const load = () => api<AppConfig>('/app-config')
      .then(c => { if (!cancelled) setConfig(c); })
      .catch((e: { status?: number }) => {
        if (cancelled || e?.status === 404) return;  // 404 = older backend without site modes: demo
        timer = setTimeout(load, delay);
        delay = Math.min(delay * 2, 30000);
      });
    load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);
  return <ConfigCtx.Provider value={config}>{children}</ConfigCtx.Provider>;
}

/** Mailto link to the owner, pre-filled with a demo request. */
export function ContactLink({ className }: { className?: string }) {
  const { contact_email } = useAppConfig();
  return (
    <a href={`mailto:${contact_email}?subject=${encodeURIComponent('FinSight AI - live demo request')}`}
      className={cn('font-medium text-primary underline-offset-2 hover:underline', className)}>{contact_email}</a>
  );
}

/** Slim banner shown across the top of every page in inspect mode. */
export function InspectBanner() {
  const inspect = useInspectMode();
  if (!inspect) return null;
  return (
    <div role="status" className="flex shrink-0 flex-wrap items-center justify-center gap-x-1.5 gap-y-0.5 border-b border-warn/25 bg-warn/[0.08] px-4 py-2 text-center text-[12.5px] text-fg-2">
      <Eye className="h-3.5 w-3.5 shrink-0 text-warn" />
      <span><span className="font-semibold text-fg">Inspect mode</span> - live AI analysis is turned off to save LLM credits. For a live demo, kindly contact</span>
      <ContactLink />
    </div>
  );
}

/** Larger notice used in place of the chat box and other LLM-powered controls. */
export function InspectNotice({ className, children }: { className?: string; children?: ReactNode }) {
  return (
    <div className={cn('rounded-2xl border border-warn/25 bg-warn/[0.06] p-4 text-left', className)}>
      <div className="flex items-center gap-2 text-sm font-semibold text-fg"><Eye className="h-4 w-4 text-warn" />Inspect mode - live AI is paused</div>
      <p className="mt-1.5 text-[13px] leading-relaxed text-fg-2">
        {children ?? <>To save LLM credits, new questions can't be sent on this public deployment. You can still explore the app and open the saved conversations to see full multi-agent answers with their sources.</>}
      </p>
      <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[13px] text-fg-2"><Mail className="h-3.5 w-3.5 text-muted" />For a live demo, kindly contact <ContactLink /></p>
    </div>
  );
}
