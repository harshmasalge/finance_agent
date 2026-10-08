import { useEffect, useMemo, useState } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ArrowRight, Bell, Briefcase, LineChart as LineIcon, Sparkles, TrendingDown, TrendingUp, Wallet } from 'lucide-react';
import { api, type AlertItem, type Holding, type HistoryPoint } from '../lib/api';
import { cn, fmtINR, fmtPct, signClass, tickerLabel, timeAgo } from '../lib/format';
import { useChartColors } from '../lib/theme';
import { useApp } from '../lib/user';
import { Badge, Button, Card, CardHeader, EmptyState, PageHeader, Skeleton, Stat } from './ui';

export default function Dashboard({ onNavigate }: { onNavigate: (t: 'portfolio' | 'advisor' | 'alerts') => void }) {
  const { user, livePrices } = useApp();
  const colors = useChartColors();
  const [holdings, setHoldings] = useState<Holding[] | null>(null);
  const [history, setHistory] = useState<HistoryPoint[] | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[] | null>(null);

  useEffect(() => {
    api<Holding[]>('/portfolio/holdings').then(setHoldings).catch(() => setHoldings([]));
    api<HistoryPoint[]>('/portfolio/history').then(setHistory).catch(() => setHistory([]));
    api<AlertItem[]>('/alerts').then(a => setAlerts(a.slice(0, 5))).catch(() => setAlerts([]));
  }, []);

  const rows = useMemo(() => (holdings ?? []).map(h => {
    const price = livePrices[h.ticker] ?? h.current_price;
    const value = price * h.quantity;
    const cost = h.avg_cost * h.quantity;
    return { ...h, price, value, cost, pnl: value - cost, pnlPct: cost ? (value - cost) / cost * 100 : 0 };
  }), [holdings, livePrices]);

  const invested = rows.reduce((s, r) => s + r.cost, 0);
  const marketValue = rows.reduce((s, r) => s + r.value, 0);
  const pnl = marketValue - invested;
  const pnlPct = invested ? pnl / invested * 100 : 0;
  const cash = user?.balance ?? 0;
  const loading = holdings === null;
  const sorted = [...rows].sort((a, b) => b.value - a.value);

  return (
    <div className="mx-auto max-w-[1280px] px-6 py-8 lg:px-10">
      <PageHeader
        title={`Good ${greeting()}, investor`}
        subtitle="Your paper portfolio at a glance"
        actions={<Button onClick={() => onNavigate('advisor')}><Sparkles className="h-4 w-4" />Ask the advisor</Button>}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Account value" icon={<Wallet className="h-4 w-4" />} loading={loading}
          value={fmtINR(cash + marketValue, true)} sub={<span className="text-muted">Cash + holdings</span>} />
        <Stat label="Unrealised P&L" icon={pnl >= 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />} loading={loading}
          value={<span className={signClass(pnl)}>{pnl >= 0 ? '+' : ''}{fmtINR(pnl, true)}</span>}
          sub={<span className={signClass(pnl)}>{fmtPct(pnlPct)} on {fmtINR(invested, true)} invested</span>} />
        <Stat label="Holdings value" icon={<Briefcase className="h-4 w-4" />} loading={loading}
          value={fmtINR(marketValue, true)} sub={<span className="text-muted">{rows.length} position{rows.length === 1 ? '' : 's'}</span>} />
        <Stat label="Available cash" icon={<Wallet className="h-4 w-4" />}
          value={fmtINR(cash, true)} sub={<span className="text-muted">{cash + marketValue ? ((cash / (cash + marketValue)) * 100).toFixed(1) : 0}% of account</span>} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Account value" subtitle="Cash plus market value of holdings since your first trade" />
          <div className="h-[300px] px-2 pb-4">
            {history === null ? <Skeleton className="mx-3 h-full" /> : history.length < 2 ? (
              <EmptyState icon={<LineIcon className="h-5 w-5" />} title="Not enough history yet"
                body="The chart fills in as you place trades and prices move." />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="valueFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={colors.series} stopOpacity={0.22} />
                      <stop offset="100%" stopColor={colors.series} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={colors.grid} vertical={false} />
                  <XAxis dataKey="time" stroke={colors.axis} fontSize={11} tickLine={false} axisLine={false} minTickGap={40} />
                  <YAxis stroke={colors.axis} fontSize={11} tickLine={false} axisLine={false} width={64} domain={['auto', 'auto']}
                    tickFormatter={v => `₹${(Number(v) / 1000).toFixed(0)}k`} />
                  <Tooltip
                    cursor={{ stroke: colors.axis, strokeDasharray: '3 3' }}
                    contentStyle={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: 10, fontSize: 12, color: colors.fg }}
                    labelStyle={{ color: colors.axis, marginBottom: 4 }}
                    formatter={v => [fmtINR(Number(v)), 'Account value']}
                  />
                  <Area type="monotone" dataKey="TotalValue" stroke={colors.series} strokeWidth={2} fill="url(#valueFill)"
                    activeDot={{ r: 4, strokeWidth: 2, stroke: colors.surface }} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Allocation" subtitle="Share of holdings by market value"
            action={<Button variant="ghost" size="sm" onClick={() => onNavigate('portfolio')}>Manage<ArrowRight className="h-3.5 w-3.5" /></Button>} />
          <div className="space-y-3.5 px-5 pb-5">
            {loading ? [0, 1, 2].map(i => <Skeleton key={i} className="h-9" />) : sorted.length === 0 ? (
              <EmptyState icon={<Briefcase className="h-5 w-5" />} title="No holdings" body="Place a paper trade to start tracking." />
            ) : sorted.map(r => {
              const w = marketValue ? r.value / marketValue * 100 : 0;
              return (
                <div key={r.ticker} className="group">
                  <div className="flex items-baseline justify-between text-[13px]">
                    <span className="font-medium text-fg">{tickerLabel(r.ticker)}</span>
                    <span className="tabular text-muted"><span className="text-fg">{w.toFixed(1)}%</span> · <span className={signClass(r.pnlPct)}>{fmtPct(r.pnlPct)}</span></span>
                  </div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2">
                    <div className={cn('h-full rounded-full transition-[width] duration-500', w > 30 ? 'bg-warn' : 'bg-primary')} style={{ width: `${w}%` }} />
                  </div>
                </div>
              );
            })}
            {sorted.some(r => marketValue && r.value / marketValue > 0.3) && (
              <p className="pt-1 text-[12px] text-warn">Amber bars hold more than 30% of the portfolio.</p>
            )}
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2 overflow-hidden">
          <CardHeader title="Holdings" subtitle="Live prices update during market hours" />
          {loading ? <div className="space-y-2 px-5 pb-5">{[0, 1, 2].map(i => <Skeleton key={i} className="h-10" />)}</div> : rows.length === 0 ? (
            <EmptyState icon={<Briefcase className="h-5 w-5" />} title="No positions yet" action={<Button variant="outline" onClick={() => onNavigate('portfolio')}>Place a trade</Button>} />
          ) : (
            <table className="w-full text-sm">
              <thead><tr className="border-y border-border bg-surface-2/60 text-left text-[12px] font-medium text-muted">
                <th className="px-5 py-2.5">Stock</th><th className="px-3 py-2.5 text-right">Price</th><th className="px-3 py-2.5 text-right">Value</th><th className="px-5 py-2.5 text-right">P&L</th>
              </tr></thead>
              <tbody>
                {sorted.map(r => (
                  <tr key={r.ticker} className="border-b border-border last:border-0 transition-colors hover:bg-surface-2/60">
                    <td className="px-5 py-3"><div className="font-medium">{tickerLabel(r.ticker)}</div><div className="text-[12px] text-muted tabular">{r.quantity} @ {fmtINR(r.avg_cost)}</div></td>
                    <td className="px-3 py-3 text-right tabular">{fmtINR(r.price)}</td>
                    <td className="px-3 py-3 text-right tabular">{fmtINR(r.value, true)}</td>
                    <td className={cn('px-5 py-3 text-right tabular font-medium', signClass(r.pnl))}>{fmtPct(r.pnlPct)}<div className="text-[12px] font-normal">{r.pnl >= 0 ? '+' : ''}{fmtINR(r.pnl, true)}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card>
          <CardHeader title="Recent alerts" action={<Button variant="ghost" size="sm" onClick={() => onNavigate('alerts')}>View all<ArrowRight className="h-3.5 w-3.5" /></Button>} />
          <div className="px-3 pb-3">
            {alerts === null ? <div className="space-y-2 px-2">{[0, 1].map(i => <Skeleton key={i} className="h-14" />)}</div> : alerts.length === 0 ? (
              <EmptyState icon={<Bell className="h-5 w-5" />} title="All quiet" body="The monitor checks your holdings every 15 minutes in market hours." />
            ) : alerts.map(a => (
              <div key={a.id} className="rounded-xl px-2 py-2.5 transition-colors hover:bg-surface-2">
                <div className="flex items-center gap-2">
                  {!a.is_read && <span className="h-1.5 w-1.5 rounded-full bg-primary" />}
                  <span className="text-[13px] font-medium">{tickerLabel(a.ticker)}</span>
                  <Badge tone={a.signal === 'SELL' ? 'down' : a.signal === 'BUY' ? 'up' : 'warn'}>{a.signal}</Badge>
                  <span className="ml-auto text-[11px] text-muted">{timeAgo(a.created_at)}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-[12.5px] text-muted">{a.message}</p>
                {(a.citations?.length ?? 0) > 0 && (
                  <button type="button" onClick={() => onNavigate('alerts')} className="mt-1 text-[11.5px] font-medium text-primary hover:underline">
                    {a.citations!.length} source{a.citations!.length === 1 ? '' : 's'}
                  </button>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening';
}
