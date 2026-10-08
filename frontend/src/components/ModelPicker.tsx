import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Cpu, RotateCcw } from 'lucide-react';
import { cn } from '../lib/format';
import { modelName, useLlm } from '../lib/llm';

/**
 * Always-visible indicator of the LLM the agents will use, doubling as a picker.
 * variant "sidebar" = full-width card, "compact" = pill for headers, "icon" = collapsed sidebar.
 */
export default function ModelPicker({ variant = 'compact', align = 'left', direction = 'down', chatId }:
  { variant?: 'sidebar' | 'compact' | 'icon'; align?: 'left' | 'right'; direction?: 'up' | 'down';
    /** Set on an open chat: the picker then chooses the model for that chat only. */
    chatId?: number | null }) {
  const llm = useLlm();
  const { providers, serverDefault, warnings, source, loaded } = llm;
  const perChat = chatId !== undefined && chatId !== null;
  const chat = perChat ? llm.forChat(chatId) : null;
  const current = chat ? chat.selection : llm.current;
  const isOverride = chat ? chat.isChatPick : llm.isOverride;
  // Per chat, "reset" means: follow the default for new chats again.
  const fallback = perChat ? llm.current : serverDefault;
  const choose = (sel: { provider: string; model: string } | null) => (perChat ? llm.chooseForChat(chatId!, sel) : llm.choose(sel));
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDoc); window.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); window.removeEventListener('keydown', onKey); };
  }, [open]);

  const label = current ? `${current.label ?? current.provider} · ${modelName(current.model)}` : loaded ? 'No model available' : 'Loading model…';
  const free = current?.model.endsWith(':free');
  const warn = warnings.length > 0;
  const title = perChat
    ? `Model for this chat: ${current?.model ?? 'unknown'}${isOverride ? ' (picked for this chat)' : ' (default for new chats)'}`
    : `Default model for new chats: ${current?.model ?? 'unknown'}${isOverride ? ' (your choice)' : ' (server default)'}`;

  const trigger = variant === 'icon' ? (
    <button onClick={() => setOpen(o => !o)} title={title} aria-label="Model"
      className="relative grid h-9 w-9 place-items-center rounded-lg text-fg-2 transition-colors hover:bg-surface-2 hover:text-fg">
      <Cpu className="h-[18px] w-[18px]" />
      {warn && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-warn" />}
    </button>
  ) : variant === 'sidebar' ? (
    <button onClick={() => setOpen(o => !o)} title={title}
      className="w-full rounded-xl bg-surface-2 px-3 py-2.5 text-left transition-colors hover:bg-surface-3">
      <div className="flex items-center justify-between text-[11px] font-medium text-muted">
        <span className="flex items-center gap-1.5"><Cpu className="h-3 w-3" />Default model{isOverride ? ' · your pick' : ''}</span>
        {warn ? <AlertTriangle className="h-3.5 w-3.5 text-warn" /> : <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />}
      </div>
      <div className="mt-0.5 truncate text-[13px] font-semibold text-fg">{modelName(current?.model)}</div>
      <div className="truncate text-[11px] text-muted">{current?.label ?? current?.provider ?? '—'}{free ? ' · free tier' : ''}</div>
    </button>
  ) : (
    <button onClick={() => setOpen(o => !o)} title={title}
      className={cn('inline-flex max-w-[320px] items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] font-medium transition-colors',
        warn ? 'border-warn/40 bg-warn/10 text-warn' : 'border-border bg-surface text-fg-2 hover:border-border-strong hover:text-fg')}>
      {warn ? <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> : <Cpu className="h-3.5 w-3.5 shrink-0" />}
      <span className="truncate">{label}</span>
      <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 transition-transform', open && 'rotate-180')} />
    </button>
  );

  return (
    <div ref={ref} className={cn('relative', variant === 'sidebar' && 'w-full')}>
      {trigger}
      {open && (
        <div className={cn('absolute z-50 w-[320px] rounded-xl border border-border bg-surface p-2 shadow-[var(--shadow-pop)] animate-fade-in',
          direction === 'up' ? 'bottom-full mb-2' : 'top-full mt-2', align === 'right' ? 'right-0' : 'left-0')} role="menu">
          <div className="px-2 pb-2 pt-1 text-[11px] text-muted">
            {perChat ? <>Used for this chat only - other chats keep their own model. Default for new chats: <span className="font-medium text-fg-2">{fallback ? `${fallback.label ?? fallback.provider} · ${modelName(fallback.model)}` : '—'}</span>.<br /></> : 'Default for new chats. '}Server default: <span className="font-medium text-fg-2">{serverDefault ? `${serverDefault.label} · ${modelName(serverDefault.model)}` : '—'}</span>
            {source && <> (from {source})</>}
          </div>
          {warn && (
            <div className="mb-2 rounded-lg border border-warn/30 bg-warn/10 p-2 text-[11.5px] leading-snug text-fg-2">
              {warnings.map((w, i) => <p key={i}>{w}</p>)}
            </div>
          )}
          <div className="max-h-[320px] overflow-y-auto">
            {providers.map(p => (
              <div key={p.id} className="py-1">
                <div className="flex items-center justify-between px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted">
                  <span>{p.label}</span><span className="font-normal normal-case tracking-normal">{p.available ? p.note : 'no API key in .env'}</span>
                </div>
                {p.models.map(m => {
                  const active = current?.provider === p.id && current?.model === m;
                  return (
                    <button key={m} disabled={!p.available} role="menuitemradio" aria-checked={active}
                      onClick={() => { choose(fallback?.provider === p.id && fallback?.model === m ? null : { provider: p.id, model: m }); setOpen(false); }}
                      className={cn('flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] transition-colors disabled:cursor-not-allowed disabled:opacity-40',
                        active ? 'bg-primary/10 text-primary' : 'text-fg-2 hover:bg-surface-2 hover:text-fg')}>
                      <span className="grid h-4 w-4 shrink-0 place-items-center">{active && <Check className="h-3.5 w-3.5" />}</span>
                      <span className="truncate">{modelName(m)}</span>
                      {serverDefault?.provider === p.id && serverDefault?.model === m && <span className="ml-auto shrink-0 text-[10.5px] text-muted">default</span>}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          {isOverride && (
            <button onClick={() => { choose(null); setOpen(false); }}
              className="mt-1 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-[12.5px] text-muted transition-colors hover:bg-surface-2 hover:text-fg">
              <RotateCcw className="h-3.5 w-3.5" />{perChat ? 'Use the default for new chats' : 'Use server default'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
