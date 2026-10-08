import { useEffect, useState, type ReactNode } from 'react';
import { Bell, Briefcase, Loader2, FileCheck2, FlaskConical, LayoutDashboard, Library, Moon, Network, PanelLeftClose, PanelLeftOpen, Sparkles, Sun, WifiOff } from 'lucide-react';
import Dashboard from './components/Dashboard';
import Portfolio from './components/Portfolio';
import Alerts from './components/Alerts';
import Advisor from './components/AIChat';
import ResearchNotes from './components/ResearchNotes';
import KnowledgeBase from './components/KnowledgeBase';
import Evaluation from './components/Evaluation';
import Architecture from './components/Architecture';
import { Button, Skeleton } from './components/ui';
import { ToastProvider, useToast } from './components/toast';
import { ThemeProvider, useTheme } from './lib/theme';
import { AppDataProvider, useApp } from './lib/user';
import { AppConfigProvider, InspectBanner } from './lib/appConfig';
import { LlmProvider } from './lib/llm';
import ModelPicker from './components/ModelPicker';
import { cn, fmtINR } from './lib/format';
import { RouterProvider, pathFor, useRouter, type Tab } from './lib/router';
import { AdvisorRunsProvider, useAdvisorRuns } from './lib/advisorRuns';

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AppConfigProvider>
          <AppDataProvider>
          <LlmProvider>
          <RouterProvider>
          <AdvisorRunsProvider>
            <Shell />
          </AdvisorRunsProvider>
          </RouterProvider>
          </LlmProvider>
          </AppDataProvider>
        </AppConfigProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}

function Shell() {
  const { user, loading, error, reload, unreadAlerts, wsConnected } = useApp();
  const { theme, toggle } = useTheme();
  const { tab, navigate, linkClick } = useRouter();
  const { runs, lastFinished } = useAdvisorRuns();
  const toast = useToast();
  const [collapsed, setCollapsed] = useState(false);
  const go = (t: Tab) => navigate(pathFor(t));
  const working = runs.filter(r => r.status === 'running').length;

  // Tell the user when an answer lands while they're on another screen.
  useEffect(() => {
    if (lastFinished && tab !== 'advisor' && Date.now() - lastFinished.at < 2000)
      toast('success', 'The advisor has answered', lastFinished.question);
  }, [lastFinished]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const label = { dashboard: 'Dashboard', portfolio: 'Portfolio', advisor: 'AI Advisor', notes: 'Research Notes', kb: 'Knowledge Base', evals: 'Evaluation', alerts: 'Alerts', architecture: 'Architecture' }[tab];
    document.title = `${label} · FinSight`;
  }, [tab]);

  if (!user) {
    return (
      <div className="grid h-full place-items-center bg-bg p-6">
        {loading ? (
          <div className="w-full max-w-sm space-y-3"><Skeleton className="h-6 w-40" /><Skeleton className="h-24 w-full" /></div>
        ) : (
          <div className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 text-center shadow-[var(--shadow-pop)] animate-fade-in-up">
            <div className="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-xl bg-down/10 text-down"><WifiOff className="h-5 w-5" /></div>
            <h2 className="text-lg font-semibold">Can't reach the FinSight API</h2>
            <p className="mt-2 text-sm text-muted">Start the backend with <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[12px]">start_app.ps1</code>, then retry.</p>
            {error && <p className="mt-3 break-words text-xs text-down">{error}</p>}
            <Button className="mt-6 w-full" onClick={reload}>Retry</Button>
          </div>
        )}
      </div>
    );
  }

  const nav: { id: Tab; label: string; icon: ReactNode; badge?: number; busy?: boolean }[] = [
    { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard className="h-[18px] w-[18px]" /> },
    { id: 'portfolio', label: 'Portfolio', icon: <Briefcase className="h-[18px] w-[18px]" /> },
    { id: 'advisor', label: 'AI Advisor', icon: <Sparkles className="h-[18px] w-[18px]" />, busy: working > 0 },
    { id: 'notes', label: 'Research Notes', icon: <FileCheck2 className="h-[18px] w-[18px]" /> },
    { id: 'kb', label: 'Knowledge Base', icon: <Library className="h-[18px] w-[18px]" /> },
    { id: 'evals', label: 'Evaluation', icon: <FlaskConical className="h-[18px] w-[18px]" /> },
    { id: 'alerts', label: 'Alerts', icon: <Bell className="h-[18px] w-[18px]" />, badge: unreadAlerts },
    { id: 'architecture', label: 'Architecture', icon: <Network className="h-[18px] w-[18px]" /> },
  ];

  return (
    <div className="flex h-full bg-bg text-fg">
      <aside className={cn('flex shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-200 ease-out', collapsed ? 'w-[68px]' : 'w-[232px]')}>
        <div className="flex h-16 items-center gap-2.5 px-4">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-fg shadow-sm">
            <svg viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M3 17l6-6 4 4 8-8" /><path d="M14 7h7v7" /></svg>
          </div>
          {!collapsed && <div className="min-w-0"><div className="text-[15px] font-semibold tracking-tight">FinSight</div><div className="-mt-0.5 text-[11px] text-muted">Agentic research · NSE</div></div>}
        </div>

        <nav className="flex-1 space-y-0.5 px-3 pt-2">
          {nav.map(n => (
            <a
              key={n.id}
              href={pathFor(n.id)}
              onClick={linkClick(pathFor(n.id))}
              aria-current={tab === n.id ? 'page' : undefined}
              title={n.busy ? `${n.label} - agents are working` : collapsed ? n.label : undefined}
              className={cn(
                'group relative flex h-10 w-full items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors duration-150',
                tab === n.id ? 'bg-primary/10 text-primary' : 'text-fg-2 hover:bg-surface-2 hover:text-fg')}
            >
              {tab === n.id && <span className="absolute -left-3 top-2 bottom-2 w-[3px] rounded-r bg-primary" />}
              <span className="shrink-0">{n.icon}</span>
              {!collapsed && <span className="truncate">{n.label}</span>}
              {n.busy && (
                <Loader2 aria-label="Agents working" className={cn('h-3.5 w-3.5 animate-spin text-primary', collapsed ? 'absolute right-1.5 top-1.5' : 'ml-auto')} />
              )}
              {!!n.badge && (
                <span className={cn('grid min-w-[18px] h-[18px] place-items-center rounded-full bg-down px-1 text-[10px] font-bold text-white', collapsed ? 'absolute right-1.5 top-1' : 'ml-auto')}>
                  {n.badge > 99 ? '99+' : n.badge}
                </span>
              )}
            </a>
          ))}
        </nav>

        <div className="space-y-2 border-t border-border p-3">
          {!collapsed && <ModelPicker variant="sidebar" direction="up" />}
          {!collapsed && (
            <div className="rounded-xl bg-surface-2 px-3 py-2.5">
              <div className="flex items-center justify-between text-[11px] font-medium text-muted">
                <span>Paper cash</span>
                <span className="flex items-center gap-1.5">
                  <span className={cn('h-1.5 w-1.5 rounded-full', wsConnected ? 'bg-up animate-pulse-dot' : 'bg-muted')} />
                  {wsConnected ? 'Live' : 'Offline'}
                </span>
              </div>
              <div className="mt-0.5 text-[15px] font-semibold tabular">{fmtINR(user.balance)}</div>
            </div>
          )}
          {collapsed ? (
            <div className="flex flex-col items-center gap-1">
              <ModelPicker variant="icon" direction="up" />
              <Button variant="ghost" size="icon" onClick={toggle} title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} aria-label="Toggle theme">
                {theme === 'dark' ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}
              </Button>
              <Button variant="ghost" size="icon" onClick={() => setCollapsed(false)} title="Expand sidebar" aria-label="Expand sidebar"><PanelLeftOpen className="h-[18px] w-[18px]" /></Button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="flex flex-1 rounded-lg border border-border bg-surface-2 p-0.5" role="radiogroup" aria-label="Theme">
                {(['light', 'dark'] as const).map(t => (
                  <button key={t} role="radio" aria-checked={theme === t} onClick={() => theme !== t && toggle()}
                    className={cn('flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 text-[12.5px] font-medium transition-all duration-150',
                      theme === t ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg')}>
                    {t === 'light' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}{t === 'light' ? 'Light' : 'Dark'}
                  </button>
                ))}
              </div>
              <Button variant="ghost" size="icon" onClick={() => setCollapsed(true)} title="Collapse sidebar" aria-label="Collapse sidebar"><PanelLeftClose className="h-[18px] w-[18px]" /></Button>
            </div>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
      <InspectBanner />
      <main className={cn('min-h-0 min-w-0 flex-1', tab === 'advisor' ? 'overflow-hidden' : 'overflow-y-auto')}>
        <div key={tab} className="h-full animate-fade-in">
          {tab === 'dashboard' && <Dashboard onNavigate={go} />}
          {tab === 'portfolio' && <Portfolio />}
          {tab === 'alerts' && <Alerts />}
          {tab === 'notes' && <ResearchNotes />}
          {tab === 'kb' && <KnowledgeBase />}
          {tab === 'evals' && <Evaluation />}
          {tab === 'architecture' && <Architecture />}
          {tab === 'advisor' && <Advisor />}
        </div>
      </main>
      </div>
    </div>
  );
}
