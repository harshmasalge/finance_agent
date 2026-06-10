import React, { useState, useEffect } from 'react';
import { Briefcase, ArrowUpRight, ArrowDownRight, RefreshCw } from 'lucide-react';

interface Holding {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  current_value: number;
  unrealised_pnl: number;
  unrealised_pnl_pct: number;
  sl_pct: number | null;
  tg_pct: number | null;
}

interface Trade {
  id: number;
  ticker: string;
  side: string;
  quantity: number;
  fill_price: number;
  timestamp: string;
  virtual_balance_after: number;
}

export default function Portfolio() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  const [tradeForm, setTradeForm] = useState({ ticker: '', side: 'BUY', quantity: 1 });
  const [tradeStatus, setTradeStatus] = useState({ loading: false, message: '', error: false });
  
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [limitsForm, setLimitsForm] = useState({ sl_pct: '', tg_pct: '' });
  const [limitsStatus, setLimitsStatus] = useState('');

  const fetchPortfolio = async () => {
    try {
      const hRes = await fetch('http://localhost:8001/portfolio/holdings', { credentials: 'include' });
      if (hRes.ok) setHoldings(await hRes.json());
      
      const tRes = await fetch('http://localhost:8001/portfolio/trades', { credentials: 'include' });
      if (tRes.ok) setTrades(await tRes.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
  }, []);

  const handleTrade = async (e: React.FormEvent) => {
    e.preventDefault();
    setTradeStatus({ loading: true, message: '', error: false });
    try {
      const res = await fetch('http://localhost:8001/portfolio/trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          ticker: tradeForm.ticker,
          side: tradeForm.side,
          quantity: Number(tradeForm.quantity)
        })
      });
      const data = await res.json();
      if (res.ok) {
        setTradeStatus({ loading: false, message: 'Trade successful!', error: false });
        fetchPortfolio();
        setTradeForm({ ticker: '', side: 'BUY', quantity: 1 });
      } else {
        setTradeStatus({ loading: false, message: data.detail || 'Trade failed', error: true });
      }
    } catch (err) {
      setTradeStatus({ loading: false, message: 'Network error', error: true });
    }
  };

  const handleLimitsSubmit = async (ticker: string) => {
    setLimitsStatus('Saving...');
    try {
      const res = await fetch(`http://localhost:8001/portfolio/holdings/${ticker}/limits`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          sl_pct: limitsForm.sl_pct ? Number(limitsForm.sl_pct) : null,
          tg_pct: limitsForm.tg_pct ? Number(limitsForm.tg_pct) : null
        })
      });
      if (res.ok) {
        setLimitsStatus('Saved!');
        fetchPortfolio();
        setTimeout(() => {
          setExpandedRow(null);
          setLimitsStatus('');
        }, 1500);
      } else {
        setLimitsStatus('Failed to save');
      }
    } catch (e) {
      setLimitsStatus('Error saving');
    }
  };

  const totalValue = holdings.reduce((acc, h) => acc + h.current_value, 0);
  const totalCost = holdings.reduce((acc, h) => acc + (h.avg_cost * h.quantity), 0);
  const totalReturn = totalValue - totalCost;
  const returnPct = totalCost > 0 ? (totalReturn / totalCost) * 100 : 0;

  if (loading) return <div className="p-6">Loading portfolio...</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-8">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center space-x-3">
          <Briefcase className="h-8 w-8 text-primary" />
          <h1 className="text-3xl font-bold tracking-tight">Portfolio Manager</h1>
        </div>
        <button onClick={fetchPortfolio} className="p-2 rounded hover:bg-muted"><RefreshCw className="h-5 w-5" /></button>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <div className="rounded-xl border bg-card text-card-foreground shadow p-6">
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Total Invested</h3>
          <div className="text-3xl font-bold">₹{totalCost.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</div>
        </div>
        <div className="rounded-xl border bg-card text-card-foreground shadow p-6">
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Current Value</h3>
          <div className="text-3xl font-bold">₹{totalValue.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</div>
        </div>
        <div className="rounded-xl border bg-card text-card-foreground shadow p-6">
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Total Returns</h3>
          <div className={`text-3xl font-bold flex items-center ${totalReturn >= 0 ? 'text-green-500' : 'text-red-500'}`}>
            {totalReturn >= 0 ? <ArrowUpRight className="mr-2" /> : <ArrowDownRight className="mr-2" />}
            ₹{Math.abs(totalReturn).toLocaleString('en-IN', { maximumFractionDigits: 2 })} 
            <span className="text-lg ml-2 opacity-80">({returnPct.toFixed(2)}%)</span>
          </div>
        </div>
      </div>

      <div className="rounded-xl border bg-card shadow overflow-hidden">
        <div className="p-4 bg-muted/30 border-b font-semibold">Current Holdings (Click to set limits)</div>
        <table className="w-full text-left text-sm">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              <th className="px-6 py-4 font-medium">Asset</th>
              <th className="px-6 py-4 font-medium">Shares</th>
              <th className="px-6 py-4 font-medium">Avg Cost</th>
              <th className="px-6 py-4 font-medium">LTP</th>
              <th className="px-6 py-4 font-medium">Stop Loss</th>
              <th className="px-6 py-4 font-medium">Target</th>
              <th className="px-6 py-4 font-medium">Total Return</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {holdings.length === 0 && (
              <tr><td colSpan={7} className="text-center py-4 text-muted-foreground">No active holdings</td></tr>
            )}
            {holdings.map((h, i) => (
              <React.Fragment key={i}>
                <tr 
                  className="hover:bg-muted/20 transition-colors cursor-pointer"
                  onClick={() => {
                    setExpandedRow(expandedRow === h.ticker ? null : h.ticker);
                    setLimitsForm({ sl_pct: h.sl_pct?.toString() || '', tg_pct: h.tg_pct?.toString() || '' });
                    setLimitsStatus('');
                  }}
                >
                  <td className="px-6 py-4 font-medium">{h.ticker}</td>
                  <td className="px-6 py-4">{h.quantity.toFixed(2)}</td>
                  <td className="px-6 py-4">₹{h.avg_cost.toFixed(2)}</td>
                  <td className="px-6 py-4">₹{h.current_price.toFixed(2)}</td>
                  <td className="px-6 py-4">{h.sl_pct ? `${h.sl_pct}%` : '—'}</td>
                  <td className="px-6 py-4">{h.tg_pct ? `${h.tg_pct}%` : '—'}</td>
                  <td className={`px-6 py-4 flex items-center ${h.unrealised_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                    ₹{Math.abs(h.unrealised_pnl).toFixed(2)} <span className="text-xs ml-2 opacity-80">({h.unrealised_pnl_pct.toFixed(2)}%)</span>
                  </td>
                </tr>
                {expandedRow === h.ticker && (
                  <tr className="bg-muted/10">
                    <td colSpan={7} className="px-6 py-4">
                      <div className="flex items-center space-x-4">
                        <span className="text-sm font-medium">Set Limits for {h.ticker}:</span>
                        <input type="number" placeholder="Stop Loss %" className="bg-background border rounded px-2 py-1 text-sm w-32" value={limitsForm.sl_pct} onChange={e => setLimitsForm({...limitsForm, sl_pct: e.target.value})} />
                        <input type="number" placeholder="Target %" className="bg-background border rounded px-2 py-1 text-sm w-32" value={limitsForm.tg_pct} onChange={e => setLimitsForm({...limitsForm, tg_pct: e.target.value})} />
                        <button onClick={() => handleLimitsSubmit(h.ticker)} className="bg-primary text-primary-foreground px-3 py-1 rounded text-sm hover:bg-primary/90">Save</button>
                        <span className="text-sm text-muted-foreground">{limitsStatus}</span>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid md:grid-cols-2 gap-8">
        <div className="rounded-xl border bg-card shadow p-6">
          <h2 className="text-xl font-bold mb-4">Execute Trade</h2>
          <form onSubmit={handleTrade} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Ticker</label>
              <input required type="text" list="tickers" className="w-full bg-background border rounded px-3 py-2" placeholder="e.g. RELIANCE.NS" value={tradeForm.ticker} onChange={e => setTradeForm({...tradeForm, ticker: e.target.value.toUpperCase()})} />
              <datalist id="tickers">
                <option value="RELIANCE.NS">Reliance Industries</option>
                <option value="TCS.NS">Tata Consultancy Services</option>
                <option value="HDFCBANK.NS">HDFC Bank</option>
                <option value="INFY.NS">Infosys</option>
                <option value="ICICIBANK.NS">ICICI Bank</option>
                <option value="SBIN.NS">State Bank of India</option>
                <option value="BHARTIARTL.NS">Bharti Airtel</option>
                <option value="ITC.NS">ITC</option>
                <option value="KOTAKBANK.NS">Kotak Mahindra Bank</option>
                <option value="LT.NS">Larsen & Toubro</option>
                <option value="AXISBANK.NS">Axis Bank</option>
                <option value="HINDUNILVR.NS">Hindustan Unilever</option>
                <option value="MARUTI.NS">Maruti Suzuki</option>
                <option value="BAJFINANCE.NS">Bajaj Finance</option>
                <option value="ASIANPAINT.NS">Asian Paints</option>
                <option value="HCLTECH.NS">HCL Technologies</option>
                <option value="TITAN.NS">Titan Company</option>
                <option value="SUNPHARMA.NS">Sun Pharmaceutical</option>
                <option value="TATASTEEL.NS">Tata Steel</option>
                <option value="WIPRO.NS">Wipro</option>
              </datalist>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1">Side</label>
                <select className="w-full bg-background border rounded px-3 py-2" value={tradeForm.side} onChange={e => setTradeForm({...tradeForm, side: e.target.value})}>
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Quantity</label>
                <input required type="number" min="0.1" step="0.1" className="w-full bg-background border rounded px-3 py-2" value={tradeForm.quantity} onChange={e => setTradeForm({...tradeForm, quantity: Number(e.target.value)})} />
              </div>
            </div>
            <button disabled={tradeStatus.loading} className="w-full bg-primary text-primary-foreground py-2 rounded font-medium hover:bg-primary/90 disabled:opacity-50">
              {tradeStatus.loading ? 'Executing...' : 'Place Order'}
            </button>
            {tradeStatus.message && (
              <div className={`text-sm p-2 rounded ${tradeStatus.error ? 'bg-red-500/20 text-red-500' : 'bg-green-500/20 text-green-500'}`}>
                {tradeStatus.message}
              </div>
            )}
          </form>
        </div>

        <div className="rounded-xl border bg-card shadow p-6 overflow-hidden flex flex-col">
          <h2 className="text-xl font-bold mb-4">Recent Trades</h2>
          <div className="overflow-y-auto max-h-[300px]">
            <table className="w-full text-left text-sm">
              <thead className="bg-muted/50 text-muted-foreground sticky top-0">
                <tr>
                  <th className="py-2">Date</th>
                  <th className="py-2">Ticker</th>
                  <th className="py-2">Side</th>
                  <th className="py-2">Qty</th>
                  <th className="py-2">Price</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {trades.length === 0 && <tr><td colSpan={5} className="py-4 text-center text-muted-foreground">No trades yet</td></tr>}
                {trades.map(t => (
                  <tr key={t.id}>
                    <td className="py-2">{new Date(t.timestamp).toLocaleDateString()}</td>
                    <td className="py-2">{t.ticker}</td>
                    <td className={`py-2 font-bold ${t.side === 'BUY' ? 'text-green-500' : 'text-red-500'}`}>{t.side}</td>
                    <td className="py-2">{t.quantity.toFixed(2)}</td>
                    <td className="py-2">₹{t.fill_price.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

    </div>
  );
}
