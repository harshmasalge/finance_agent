import { Fragment, useEffect, useState, type FormEvent } from 'react';
import { ArrowDownRight, ArrowUpRight, Briefcase, ChevronDown, History, RefreshCw, Target } from 'lucide-react';
import { api, type Holding, type Trade } from '../lib/api';
import { cn, fmtINR, fmtPct, signClass, tickerLabel } from '../lib/format';
import { useApp } from '../lib/user';
import { useToast } from './toast';
import { Badge, Button, Card, CardHeader, EmptyState, Input, Label, PageHeader, Segmented, Skeleton, Stat } from './ui';

const POPULAR = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS', 'SBIN.NS', 'BHARTIARTL.NS', 'ITC.NS', 'KOTAKBANK.NS',
  'LT.NS', 'AXISBANK.NS', 'HINDUNILVR.NS', 'MARUTI.NS', 'BAJFINANCE.NS', 'ASIANPAINT.NS', 'HCLTECH.NS', 'TITAN.NS', 'SUNPHARMA.NS',
  'TATASTEEL.NS', 'WIPRO.NS', 'TECHM.NS', 'COALINDIA.NS', 'NTPC.NS'];

export default function Portfolio() {
  const { livePrices, reload: reloadUser } = useApp();
  const toast = useToast();
  const [holdings, setHoldings] = useState<Holding[] | null>(null);
  const [trades, setTrades] = useState<Trade[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY');
  const [ticker, setTicker] = useState('');
  const [qty, setQty] = useState('1');
  const [placing, setPlacing] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [limits, setLimits] = useState({ sl: '', tg: '' });
  const [savingLimits, setSavingLimits] = useState(false);

  const load = async () => {
    setRefreshing(true);
    try {
      const [h, t] = await Promise.all([api<Holding[]>('/portfolio/holdings'), api<Trade[]>('/portfolio/trades')]);
      setHoldings(h); setTrades(t);
    } catch (e) {
      toast('error', 'Could not load portfolio', String((e as Error).message));
      setHoldings(h => h ?? []); setTrades(t => t ?? []);
    } finally { setRefreshing(false); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = (holdings ?? []).map(h => {
    const price = livePrices[h.ticker] ?? h.current_price;
    const value = price * h.quantity, cost = h.avg_cost * h.quantity;
    return { ...h, price, value, cost, pnl: value - cost, pnlPct: cost ? (value - cost) / cost * 100 : 0 };
  });
  const invested = rows.reduce((s, r) => s + r.cost, 0);
  const value = rows.reduce((s, r) => s + r.value, 0);
  const pnl = value - invested;

  const placeTrade = async (e: FormEvent) => {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    const symbol = t.endsWith('.NS') || t.endsWith('.BO') ? t : `${t}.NS`;
    setPlacing(true);
    try {
      const res = await api<Trade>('/portfolio/trade', { method: 'POST', body: JSON.stringify({ ticker: symbol, side, quantity: Number(qty) }) });
      toast('success', `${side === 'BUY' ? 'Bought' : 'Sold'} ${qty} ${tickerLabel(symbol)}`, `Filled at ${fmtINR(res.fill_price)}`);
      setTicker(''); setQty('1');
      load(); reloadUser();
    } catch (err) {
      toast('error', 'Order rejected', (err as Error).message);
    } finally { setPlacing(false); }
  };

  const saveLimits = async (t: string) => {
    setSavingLimits(true);
    try {
      await api(`/portfolio/holdings/${encodeURIComponent(t)}/limits`, {
        method: 'PATCH', body: JSON.stringify({ sl_pct: limits.sl ? Number(limits.sl) : null, tg_pct: limits.tg ? Number(limits.tg) : null }) });
      toast('success', `Limits saved for ${tickerLabel(t)}`);
      setExpanded(null); load();
    } catch (err) {
      toast('error', 'Could not save limits', (err as Error).message);
    } finally { setSavingLimits(false); }
  };

  return (
    <div className="mx-auto max-w-[1280px] px-6 py-8 lg:px-10">
      <PageHeader title="Portfolio" subtitle="Paper trades at live NSE prices"
        actions={<Button variant="outline" onClick={load} loading={refreshing}>{!refreshing && <RefreshCw className="h-4 w-4" />}Refresh</Button>} />

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Invested" value={fmtINR(invested, true)} loading={holdings === null} />
        <Stat label="Current value" value={fmtINR(value, true)} loading={holdings === null} />
        <Stat label="Total return" loading={holdings === null}
          value={<span className={cn('flex items-center gap-1', signClass(pnl))}>{pnl >= 0 ? <ArrowUpRight className="h-5 w-5" /> : <ArrowDownRight className="h-5 w-5" />}{fmtINR(Math.abs(pnl), true)}</span>}
          sub={<span className={signClass(pnl)}>{fmtPct(invested ? pnl / invested * 100 : 0)}</span>} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card className="overflow-hidden">
          <CardHeader title="Holdings" subtitle="Click a row to set stop-loss and target alerts" />
          {holdings === null ? <div className="space-y-2 px-5 pb-5">{[0, 1, 2].map(i => <Skeleton key={i} className="h-11" />)}</div> : rows.length === 0 ? (
            <EmptyState icon={<Briefcase className="h-5 w-5" />} title="No holdings yet" body="Use the order ticket to buy your first stock." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead><tr className="border-y border-border bg-surface-2/60 text-left text-[12px] font-medium text-muted">
                  <th className="px-5 py-2.5">Stock</th><th className="px-3 py-2.5 text-right">Qty</th><th className="px-3 py-2.5 text-right">Avg cost</th>
                  <th className="px-3 py-2.5 text-right">LTP</th><th className="px-3 py-2.5 text-right">Value</th><th className="px-3 py-2.5 text-right">P&L</th>
                  <th className="px-3 py-2.5">Limits</th><th className="w-10" />
                </tr></thead>
                <tbody>
                  {rows.map(r => (
                    <Fragment key={r.ticker}>
                      <tr
                        onClick={() => { setExpanded(expanded === r.ticker ? null : r.ticker); setLimits({ sl: r.sl_pct?.toString() ?? '', tg: r.tg_pct?.toString() ?? '' }); }}
                        className={cn('cursor-pointer border-b border-border transition-colors hover:bg-surface-2/60', expanded === r.ticker && 'bg-surface-2/60')}>
                        <td className="px-5 py-3 font-medium">{tickerLabel(r.ticker)}<span className="ml-1.5 text-[11px] text-muted">{r.ticker.endsWith('.BO') ? 'BSE' : 'NSE'}</span></td>
                        <td className="px-3 py-3 text-right tabular">{r.quantity}</td>
                        <td className="px-3 py-3 text-right tabular">{fmtINR(r.avg_cost)}</td>
                        <td className="px-3 py-3 text-right tabular">{fmtINR(r.price)}</td>
                        <td className="px-3 py-3 text-right tabular">{fmtINR(r.value, true)}</td>
                        <td className={cn('px-3 py-3 text-right tabular font-medium', signClass(r.pnl))}>{fmtPct(r.pnlPct)}</td>
                        <td className="px-3 py-3"><div className="flex gap-1">
                          {r.sl_pct != null && <Badge tone="down">SL {r.sl_pct}%</Badge>}
                          {r.tg_pct != null && <Badge tone="up">TG {r.tg_pct}%</Badge>}
                          {r.sl_pct == null && r.tg_pct == null && <span className="text-[12px] text-muted">—</span>}
                        </div></td>
                        <td className="pr-4"><ChevronDown className={cn('h-4 w-4 text-muted transition-transform duration-200', expanded === r.ticker && 'rotate-180')} /></td>
                      </tr>
                      {expanded === r.ticker && (
                        <tr className="border-b border-border bg-surface-2/40">
                          <td colSpan={8} className="px-5 py-4">
                            <div className="flex flex-wrap items-end gap-3 animate-fade-in">
                              <div className="w-36"><Label>Stop-loss %</Label><Input type="number" min="0" step="0.5" placeholder="e.g. 8" value={limits.sl} onChange={e => setLimits({ ...limits, sl: e.target.value })} /></div>
                              <div className="w-36"><Label>Target %</Label><Input type="number" min="0" step="0.5" placeholder="e.g. 15" value={limits.tg} onChange={e => setLimits({ ...limits, tg: e.target.value })} /></div>
                              <Button onClick={() => saveLimits(r.ticker)} loading={savingLimits}><Target className="h-4 w-4" />Save limits</Button>
                              <Button variant="ghost" onClick={() => setExpanded(null)}>Cancel</Button>
                              <p className="w-full text-[12px] text-muted">The monitor alerts you when the price moves this far from your average cost.</p>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card className="h-fit">
          <CardHeader title="Order ticket" subtitle="Market order · 0.05% slippage" />
          <form onSubmit={placeTrade} className="space-y-4 px-5 pb-5">
            <Segmented value={side} onChange={setSide} className="w-full"
              options={[{ value: 'BUY', label: 'Buy', activeClass: '!bg-up !text-white' }, { value: 'SELL', label: 'Sell', activeClass: '!bg-down !text-white' }]} />
            <div>
              <Label htmlFor="ticker">Stock</Label>
              <Input id="ticker" required list="nse-tickers" placeholder="e.g. RELIANCE or TCS.NS" value={ticker} onChange={e => setTicker(e.target.value)} autoComplete="off" />
              <datalist id="nse-tickers">{POPULAR.map(t => <option key={t} value={t} />)}</datalist>
            </div>
            <div>
              <Label htmlFor="qty">Quantity</Label>
              <Input id="qty" type="number" required min="1" step="1" value={qty} onChange={e => setQty(e.target.value)} />
            </div>
            <Button type="submit" size="lg" loading={placing} className={cn('w-full', side === 'SELL' && '!bg-down hover:!brightness-110')}>
              {side === 'BUY' ? 'Place buy order' : 'Place sell order'}
            </Button>
          </form>
        </Card>
      </div>

      <Card className="mt-4 overflow-hidden">
        <CardHeader title="Trade history" subtitle="Last 50 orders" />
        {trades === null ? <div className="px-5 pb-5"><Skeleton className="h-24" /></div> : trades.length === 0 ? (
          <EmptyState icon={<History className="h-5 w-5" />} title="No trades yet" />
        ) : (
          <div className="max-h-[360px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface"><tr className="border-y border-border text-left text-[12px] font-medium text-muted">
                <th className="px-5 py-2.5">Date</th><th className="px-3 py-2.5">Stock</th><th className="px-3 py-2.5">Side</th>
                <th className="px-3 py-2.5 text-right">Qty</th><th className="px-3 py-2.5 text-right">Fill price</th><th className="px-5 py-2.5 text-right">Cash after</th>
              </tr></thead>
              <tbody>
                {trades.map(t => (
                  <tr key={t.id} className="border-b border-border last:border-0 transition-colors hover:bg-surface-2/60">
                    <td className="px-5 py-2.5 text-muted tabular">{new Date(t.timestamp).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</td>
                    <td className="px-3 py-2.5 font-medium">{tickerLabel(t.ticker)}</td>
                    <td className="px-3 py-2.5"><Badge tone={t.side === 'BUY' ? 'up' : 'down'}>{t.side}</Badge></td>
                    <td className="px-3 py-2.5 text-right tabular">{t.quantity}</td>
                    <td className="px-3 py-2.5 text-right tabular">{fmtINR(t.fill_price)}</td>
                    <td className="px-5 py-2.5 text-right tabular text-muted">{fmtINR(t.virtual_balance_after, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
