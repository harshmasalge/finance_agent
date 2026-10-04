import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '../lib/format';

// ---------------- Button ----------------
type Variant = 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger';
type Size = 'sm' | 'md' | 'lg' | 'icon' | 'icon-sm';

const variants: Record<Variant, string> = {
  primary: 'bg-primary text-primary-fg hover:bg-primary-hover shadow-sm',
  secondary: 'bg-surface-2 text-fg hover:bg-surface-3',
  ghost: 'text-fg-2 hover:bg-surface-2 hover:text-fg',
  outline: 'border border-border bg-surface text-fg hover:bg-surface-2 hover:border-border-strong',
  danger: 'bg-down text-white hover:brightness-110',
};
const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px] gap-1.5 rounded-lg',
  md: 'h-9 px-4 text-sm gap-2 rounded-lg',
  lg: 'h-11 px-5 text-sm gap-2 rounded-xl',
  icon: 'h-9 w-9 rounded-lg',
  'icon-sm': 'h-7 w-7 rounded-md',
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant; size?: Size; loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', loading, className, children, disabled, ...props }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex select-none items-center justify-center font-medium whitespace-nowrap',
        'transition-[background-color,color,border-color,box-shadow,transform,filter] duration-150 ease-out',
        'active:scale-[0.97] disabled:opacity-50 disabled:active:scale-100',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
        variants[variant], sizes[size], className)}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
});

// ---------------- Card ----------------
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-2xl border border-border bg-surface shadow-[var(--shadow-card)]', className)} {...props} />;
}
export function CardHeader({ title, subtitle, action, className }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-start justify-between gap-4 px-5 pt-5 pb-3', className)}>
      <div className="min-w-0">
        <h3 className="text-[15px] font-semibold tracking-tight text-fg">{title}</h3>
        {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

// ---------------- Badge ----------------
type Tone = 'neutral' | 'up' | 'down' | 'warn' | 'primary';
const tones: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-fg-2 border-border',
  up: 'bg-up/10 text-up border-up/20',
  down: 'bg-down/10 text-down border-down/20',
  warn: 'bg-warn/10 text-warn border-warn/25',
  primary: 'bg-primary/10 text-primary border-primary/20',
};
export function Badge({ tone = 'neutral', className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide', tones[tone], className)}>
      {children}
    </span>
  );
}

// ---------------- Inputs ----------------
const field = cn(
  'h-9 w-full rounded-lg border border-border bg-surface px-3 text-sm text-fg placeholder:text-muted',
  'transition-[border-color,box-shadow] duration-150 hover:border-border-strong',
  'focus:outline-none focus:border-primary focus:ring-3 focus:ring-primary/15');

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn(field, className)} {...p} />;
});
export function Select({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(field, 'pr-8', className)} {...p} />;
}
export function Label({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return <label htmlFor={htmlFor} className="mb-1.5 block text-[13px] font-medium text-fg-2">{children}</label>;
}

// ---------------- Misc ----------------
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton', className)} />;
}

export function EmptyState({ icon, title, body, action }: { icon: ReactNode; title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center animate-fade-in">
      <div className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-surface-2 text-muted">{icon}</div>
      <p className="text-sm font-medium text-fg">{title}</p>
      {body && <p className="mt-1 max-w-sm text-[13px] text-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, className }:
  { value: T; options: { value: T; label: ReactNode; activeClass?: string }[]; onChange: (v: T) => void; className?: string }) {
  return (
    <div className={cn('inline-flex rounded-lg border border-border bg-surface-2 p-0.5', className)} role="tablist">
      {options.map(o => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'flex-1 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all duration-150',
            value === o.value ? cn('bg-surface text-fg shadow-sm', o.activeClass) : 'text-muted hover:text-fg')}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, sub, icon, loading }: { label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode; loading?: boolean }) {
  return (
    <Card className="p-5 transition-colors hover:border-border-strong">
      <div className="flex items-center justify-between text-[13px] font-medium text-muted">
        <span>{label}</span>
        {icon && <span className="text-muted/80">{icon}</span>}
      </div>
      {loading ? <Skeleton className="mt-3 h-7 w-32" /> : (
        <div className="mt-2 text-[26px] font-semibold tracking-tight tabular text-fg">{value}</div>
      )}
      {sub && !loading && <div className="mt-1 text-[13px] tabular">{sub}</div>}
    </Card>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pb-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
