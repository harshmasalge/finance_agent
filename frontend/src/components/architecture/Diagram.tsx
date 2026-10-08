import { useEffect, useId, useState, type KeyboardEvent, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight, MousePointerClick, Pause, Play, X } from 'lucide-react';
import { cn } from '../../lib/format';
import { Button } from '../ui';
import { KIND, edgeId, type DEdge, type DNode, type Hi, type Mode, type Spec } from './types';

/* ------------------------------------------------------------------ */
/* SVG diagram: boxes, arrows, groups. Purely presentational.          */
/* ------------------------------------------------------------------ */

type Pt = [number, number];

/** Polyline with rounded corners. */
function roundedPath(pts: Pt[], r = 8): string {
  if (pts.length < 2) return '';
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
    const l1 = Math.hypot(x1 - x0, y1 - y0), l2 = Math.hypot(x2 - x1, y2 - y1);
    const rr = Math.min(r, l1 / 2, l2 / 2);
    const ax = x1 - ((x1 - x0) / l1) * rr, ay = y1 - ((y1 - y0) / l1) * rr;
    const bx = x1 + ((x2 - x1) / l2) * rr, by = y1 + ((y2 - y1) / l2) * rr;
    d += ` L${ax},${ay} Q${x1},${y1} ${bx},${by}`;
  }
  const last = pts[pts.length - 1];
  return `${d} L${last[0]},${last[1]}`;
}

const mix = (c: string, pct: number, base = 'var(--surface)') => `color-mix(in oklab, ${c} ${pct}%, ${base})`;

/** Hover highlight when no mode is active: the node, its arrows and its neighbours. */
function hoverHi(spec: Spec, id: string): Hi {
  const nodes: NonNullable<Hi>['nodes'] = { [id]: 'on' };
  const edges: NonNullable<Hi>['edges'] = {};
  for (const e of spec.edges) {
    if (e.from === id || e.to === id) {
      edges[edgeId(e)] = 'on';
      nodes[e.from === id ? e.to : e.from] ??= 'past';
    }
  }
  return { nodes, edges };
}

export function Diagram({ spec, hi, selected, onSelect, label }: {
  spec: Spec; hi: Hi; selected: string | null; onSelect: (id: string | null) => void; label: string;
}) {
  const uid = useId().replace(/:/g, '');
  const [hover, setHover] = useState<string | null>(null);
  const eff: Hi = hi ?? (hover ? hoverHi(spec, hover) : null);

  type St = 'normal' | 'on' | 'past' | 'dim';
  const nodeState = (id: string): St => (eff ? eff.nodes[id] ?? 'dim' : 'normal');
  const edgeState = (e: DEdge): St => (eff ? eff.edges[edgeId(e)] ?? 'dim' : 'normal');

  const key = (id: string) => (ev: KeyboardEvent) => {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onSelect(selected === id ? null : id); }
    if (ev.key === 'Escape') onSelect(null);
  };

  return (
    <svg viewBox={`0 0 ${spec.width} ${spec.height}`} role="group" aria-label={label}
      className="block h-auto w-full select-none" style={{ minWidth: spec.minWidth ?? 720 }}
      onClick={() => onSelect(null)}>
      <defs>
        <pattern id={`${uid}-dots`} width="20" height="20" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="0.9" style={{ fill: 'var(--border)' }} />
        </pattern>
        {(['normal', 'on', 'past', 'dim'] as const).map(s => (
          <marker key={s} id={`${uid}-arrow-${s}`} viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="8" markerHeight="8"
            markerUnits="userSpaceOnUse" orient="auto-start-reverse">
            <path d="M0,0.5 L10,5 L0,9.5 z" style={{ fill: s === 'on' ? 'var(--primary)' : 'var(--muted)', opacity: s === 'dim' ? 0.3 : 1 }} />
          </marker>
        ))}
      </defs>
      <rect width={spec.width} height={spec.height} fill={`url(#${uid}-dots)`} />

      {spec.groups?.map(g => (
        <g key={g.label}>
          <rect x={g.x} y={g.y} width={g.w} height={g.h} rx="14" strokeDasharray="5 4"
            style={{ fill: 'color-mix(in oklab, var(--fg) 2.5%, transparent)', stroke: 'var(--border-strong)' }} />
          <text x={g.lx ?? g.x + 12} y={g.ly ?? g.y + g.h - 10} fontSize="10.5" fontWeight="600" letterSpacing="0.06em"
            style={{ fill: 'var(--muted)' }}>{g.label.toUpperCase()}</text>
        </g>
      ))}

      {spec.edges.map(e => {
        const s = edgeState(e);
        const color = s === 'on' ? 'var(--primary)' : 'var(--muted)';
        return (
          <g key={edgeId(e)} style={{ opacity: s === 'dim' ? 0.28 : s === 'normal' ? 0.85 : 1, transition: 'opacity 200ms' }}>
            <path d={roundedPath(e.pts)} fill="none" strokeWidth={s === 'on' ? 2 : 1.4} strokeLinecap="round" strokeLinejoin="round"
              className={s === 'on' ? 'arch-flow' : undefined} strokeDasharray={s !== 'on' && e.dashed ? '5 4' : undefined}
              style={{ stroke: color, transition: 'stroke 200ms' }}
              markerEnd={`url(#${uid}-arrow-${s})`} markerStart={e.both ? `url(#${uid}-arrow-${s})` : undefined} />
            {e.label && e.lp && (
              <text x={e.lp[0]} y={e.lp[1]} textAnchor={e.anchor ?? 'middle'} fontSize="11" fontWeight={s === 'on' ? 600 : 500}
                style={{ fill: s === 'on' ? 'var(--primary)' : 'var(--muted)', paintOrder: 'stroke', stroke: 'var(--surface)', strokeWidth: 4, strokeLinejoin: 'round' }}>
                {e.label}
              </text>
            )}
          </g>
        );
      })}

      {spec.nodes.map(n => <NodeBox key={n.id} n={n} state={nodeState(n.id)} selected={selected === n.id}
        onClick={() => onSelect(selected === n.id ? null : n.id)} onKey={key(n.id)}
        onHover={v => setHover(v ? n.id : null)} />)}
    </svg>
  );
}

function NodeBox({ n, state, selected, onClick, onKey, onHover }: {
  n: DNode; state: 'normal' | 'on' | 'past' | 'dim'; selected: boolean;
  onClick: () => void; onKey: (e: KeyboardEvent) => void; onHover: (v: boolean) => void;
}) {
  const c = KIND[n.kind].color;
  const lit = state === 'on' || selected;
  const subs = n.sub ? n.sub.split('\n') : [];
  const blockH = 17 + subs.length * 15;
  const top = n.y + n.h / 2 - blockH / 2 + 13;
  const cx = n.x + n.w / 2 + 1.5;
  return (
    <g className="arch-node" role="button" tabIndex={0} aria-pressed={selected} aria-label={`${n.title}. ${n.summary}`}
      onClick={e => { e.stopPropagation(); onClick(); }} onKeyDown={onKey}
      onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)} onFocus={() => onHover(true)} onBlur={() => onHover(false)}
      style={{ cursor: 'pointer', opacity: state === 'dim' && !selected ? 0.3 : 1, transition: 'opacity 200ms' }}>
      <rect className="arch-focus" x={n.x - 4} y={n.y - 4} width={n.w + 8} height={n.h + 8} rx="14" fill="none"
        strokeWidth="2" style={{ stroke: 'var(--ring)', opacity: 0 }} />
      <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="10"
        strokeWidth={selected ? 2.2 : lit ? 1.6 : 1.2} strokeDasharray={n.kind === 'external' ? '4 3' : undefined}
        style={{
          fill: mix(c, lit ? 17 : state === 'past' ? 11 : 7),
          stroke: selected ? 'var(--primary)' : lit ? c : mix(c, 40, 'var(--border)'),
          transition: 'fill 200ms, stroke 200ms',
          filter: selected ? 'drop-shadow(0 4px 10px rgb(0 0 0 / 0.12))' : undefined,
        }} />
      <rect x={n.x + 6} y={n.y + 12} width="3" height={n.h - 24} rx="1.5" style={{ fill: c, opacity: 0.9 }} />
      <text x={cx} y={top} textAnchor="middle" fontSize="13.5" fontWeight="600" style={{ fill: 'var(--fg)' }}>{n.title}</text>
      {subs.map((s, i) => (
        <text key={i} x={cx} y={top + 16 + i * 15} textAnchor="middle" fontSize="11.25" style={{ fill: 'var(--muted)' }}>{s}</text>
      ))}
    </g>
  );
}

/* ------------------------------------------------------------------ */
/* Interactive wrapper: mode chips, step player, details panel.        */
/* ------------------------------------------------------------------ */

function modeHi(mode: Mode | undefined, step: number): Hi {
  if (!mode) return null;
  const nodes: NonNullable<Hi>['nodes'] = {};
  const edges: NonNullable<Hi>['edges'] = {};
  if (mode.steps?.length) {
    mode.steps.forEach((s, i) => {
      if (i > step) return;
      const v = i === step ? 'on' : 'past';
      s.nodes.forEach(n => { if (nodes[n] !== 'on') nodes[n] = v; });
      s.edges?.forEach(e => { if (edges[e] !== 'on') edges[e] = v; });
    });
  } else {
    mode.nodes?.forEach(n => { nodes[n] = 'on'; });
    mode.edges?.forEach(e => { edges[e] = 'on'; });
    mode.past?.forEach(e => { edges[e] ??= 'past'; });
  }
  return { nodes, edges };
}

export function InteractiveDiagram({ spec, label, modes = [], modesLabel = 'Show', intro, exploreLabel = 'Explore', footer, initialMode = null }: {
  spec: Spec; label: string; modes?: Mode[]; modesLabel?: string; intro: ReactNode; exploreLabel?: string;
  footer?: (modeId: string | null) => ReactNode; initialMode?: string | null;
}) {
  const [modeId, setModeId] = useState<string | null>(initialMode);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const mode = modes.find(m => m.id === modeId);
  const steps = mode?.steps ?? [];
  const hi = modeHi(mode, step);
  const node = spec.nodes.find(n => n.id === selected);

  useEffect(() => {
    if (!playing || step >= steps.length - 1) return;
    const t = window.setTimeout(() => {
      setStep(step + 1);
      if (step + 1 >= steps.length - 1) setPlaying(false);
    }, 2800);
    return () => window.clearTimeout(t);
  }, [playing, step, steps.length]);

  const pick = (id: string | null) => {
    setModeId(id); setStep(0); setSelected(null);
    setPlaying(!!modes.find(m => m.id === id)?.steps?.length);
  };
  const goStep = (i: number) => { setPlaying(false); setSelected(null); setStep(i); };

  return (
    <div className="px-5 pb-5">
      {modes.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pb-3">
          <span className="mr-1 text-[12px] font-medium text-muted">{modesLabel}</span>
          {[{ id: null as string | null, label: exploreLabel }, ...modes].map(m => (
            <button key={m.id ?? 'explore'} type="button" onClick={() => pick(m.id)} aria-pressed={modeId === m.id}
              className={cn('rounded-full border px-3 py-1 text-[12.5px] font-medium transition-colors duration-150',
                modeId === m.id ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border bg-surface text-fg-2 hover:border-border-strong hover:text-fg')}>
              {m.label}
            </button>
          ))}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <Diagram spec={spec} hi={hi} selected={selected} onSelect={setSelected} label={label} />
      </div>

      {steps.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 pt-3">
          <Button variant="outline" size="icon-sm" aria-label="Previous step" disabled={step === 0} onClick={() => goStep(step - 1)}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="icon-sm" aria-label={playing ? 'Pause' : 'Play'} onClick={() => {
            if (!playing && step >= steps.length - 1) setStep(0);
            setSelected(null);
            setPlaying(p => !p);
          }}>
            {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          </Button>
          <Button variant="outline" size="icon-sm" aria-label="Next step" disabled={step >= steps.length - 1} onClick={() => goStep(step + 1)}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <ol className="ml-1 flex flex-wrap gap-1.5">
            {steps.map((s, i) => (
              <li key={s.title}>
                <button type="button" onClick={() => goStep(i)} aria-current={i === step ? 'step' : undefined}
                  className={cn('flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors',
                    i === step ? 'bg-primary text-primary-fg' : i < step ? 'bg-primary/10 text-primary' : 'bg-surface-2 text-muted hover:text-fg')}>
                  <span className="tabular">{i + 1}</span><span className="hidden sm:inline">{s.title}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="mt-3 min-h-[88px] rounded-xl bg-surface-2 px-4 py-3.5 text-[13px] leading-relaxed text-fg-2" aria-live="polite">
        {node ? (
          <div key={node.id} className="animate-fade-in">
            <div className="flex items-start justify-between gap-2">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <h4 className="text-[14.5px] font-semibold text-fg">{node.title}</h4>
                <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: KIND[node.kind].color }}>{KIND[node.kind].label}</span>
              </div>
              <Button variant="ghost" size="icon-sm" className="-mt-1 -mr-1" aria-label="Close details" onClick={() => setSelected(null)}><X className="h-4 w-4" /></Button>
            </div>
            <div className={cn('mt-1 grid gap-x-8 gap-y-2', node.points && 'md:grid-cols-2')}>
              <p>{node.summary}</p>
              {node.points && (
                <ul className="space-y-1">
                  {node.points.map(p => (
                    <li key={p} className="flex gap-2"><span className="mt-[8px] h-1 w-1 shrink-0 rounded-full bg-muted" /><span>{p}</span></li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ) : mode ? (
          <div key={`${mode.id}-${step}`} className="animate-fade-in">
            {steps.length > 0 ? (
              <>
                <h4 className="text-[14.5px] font-semibold text-fg"><span className="text-primary tabular">{step + 1}/{steps.length}</span> {steps[step].title}</h4>
                <p className="mt-1">{steps[step].text}</p>
              </>
            ) : (
              <>
                <h4 className="text-[14.5px] font-semibold text-fg">{mode.label}</h4>
                <div className="mt-1">{mode.summary}</div>
              </>
            )}
            <p className="mt-2 flex items-center gap-1.5 text-[12px] text-muted"><MousePointerClick className="h-3.5 w-3.5" />Click any box for details.</p>
          </div>
        ) : (
          <div className="animate-fade-in">
            {intro}
            <p className="mt-2 flex items-center gap-1.5 text-[12px] text-muted"><MousePointerClick className="h-3.5 w-3.5" />Click any box for details, or hover to see its connections.</p>
          </div>
        )}
      </div>
      {footer?.(modeId)}
    </div>
  );
}
