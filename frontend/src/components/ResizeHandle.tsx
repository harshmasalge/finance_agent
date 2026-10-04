import { useCallback, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { cn } from '../lib/format';

/**
 * Vertical drag handle between two panels.
 * `side` says which neighbour is being resized: 'left' grows as you drag right, 'right' grows as you drag left.
 */
export default function ResizeHandle({ width, onChange, min, max, side, onReset, label }:
  { width: number; onChange: (w: number) => void; min: number; max: number; side: 'left' | 'right'; onReset?: () => void; label: string }) {
  const start = useRef<{ x: number; w: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const clamp = useCallback((w: number) => Math.round(Math.min(max, Math.max(min, w))), [min, max]);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    start.current = { x: e.clientX, w: width };
    setDragging(true);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    const dx = e.clientX - start.current.x;
    onChange(clamp(start.current.w + (side === 'left' ? dx : -dx)));
  };
  const end = () => {
    start.current = null;
    setDragging(false);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 64 : 16;
    if (e.key === 'ArrowLeft') { e.preventDefault(); onChange(clamp(width + (side === 'left' ? -step : step))); }
    if (e.key === 'ArrowRight') { e.preventDefault(); onChange(clamp(width + (side === 'left' ? step : -step))); }
  };

  return (
    <div
      role="separator" aria-orientation="vertical" aria-label={label} aria-valuenow={width} aria-valuemin={min} aria-valuemax={max}
      tabIndex={0}
      title={`${label} — drag to resize, double-click to reset`}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={end} onPointerCancel={end}
      onDoubleClick={onReset} onKeyDown={onKeyDown}
      className="group relative z-10 -mx-[5px] w-[11px] shrink-0 cursor-col-resize touch-none select-none focus-visible:outline-none"
    >
      <span className={cn('absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-all duration-150',
        'group-hover:w-[3px] group-hover:bg-primary/60 group-focus-visible:w-[3px] group-focus-visible:bg-primary',
        dragging && '!w-[3px] !bg-primary')} />
      <span className={cn('absolute left-1/2 top-1/2 flex h-8 w-1.5 -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center gap-0.5 rounded-full bg-surface opacity-0 shadow ring-1 ring-border transition-opacity group-hover:opacity-100',
        dragging && 'opacity-100')}>
        <span className="h-0.5 w-0.5 rounded-full bg-muted" /><span className="h-0.5 w-0.5 rounded-full bg-muted" /><span className="h-0.5 w-0.5 rounded-full bg-muted" />
      </span>
    </div>
  );
}
