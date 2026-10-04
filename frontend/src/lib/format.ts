const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });

export const fmtINR = (v: number, compact = false) => (Number.isFinite(v) ? (compact ? inr0 : inr).format(v) : '—');
export const fmtPct = (v: number, signed = true) =>
  Number.isFinite(v) ? `${signed && v > 0 ? '+' : ''}${v.toFixed(2)}%` : '—';
export const fmtNum = (v: number, d = 2) =>
  Number.isFinite(v) ? v.toLocaleString('en-IN', { maximumFractionDigits: d }) : '—';
export const signClass = (v: number) => (v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-muted');

export function timeAgo(iso?: string | null) {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 604800) return `${Math.floor(s / 86400)}d ago`;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ');
}

export const tickerLabel = (t: string) => t.replace(/\.(NS|BO)$/, '');
