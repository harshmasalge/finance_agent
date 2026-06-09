import { Briefcase, ArrowUpRight, ArrowDownRight } from 'lucide-react';

const mockHoldings = [
  { ticker: 'RELIANCE.NS', shares: 50, avgCost: 2400.50, currentPrice: 2500.25 },
  { ticker: 'TCS.NS', shares: 15, avgCost: 3500.00, currentPrice: 3450.10 },
  { ticker: 'HDFCBANK.NS', shares: 100, avgCost: 1600.75, currentPrice: 1650.00 }
];

export default function Portfolio() {
  const totalValue = mockHoldings.reduce((acc, h) => acc + (h.shares * h.currentPrice), 0);
  const totalCost = mockHoldings.reduce((acc, h) => acc + (h.shares * h.avgCost), 0);
  const totalReturn = totalValue - totalCost;
  const returnPct = (totalReturn / totalCost) * 100;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-8">
      <div className="flex items-center space-x-3 mb-2">
        <Briefcase className="h-8 w-8 text-primary" />
        <h1 className="text-3xl font-bold tracking-tight">Portfolio Manager</h1>
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
        <table className="w-full text-left text-sm">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              <th className="px-6 py-4 font-medium">Asset</th>
              <th className="px-6 py-4 font-medium">Shares</th>
              <th className="px-6 py-4 font-medium">Avg Cost</th>
              <th className="px-6 py-4 font-medium">LTP</th>
              <th className="px-6 py-4 font-medium">Total Return</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {mockHoldings.map((h, i) => {
              const ret = (h.currentPrice - h.avgCost) * h.shares;
              const retPct = ((h.currentPrice - h.avgCost) / h.avgCost) * 100;
              return (
                <tr key={i} className="hover:bg-muted/20 transition-colors">
                  <td className="px-6 py-4 font-medium">{h.ticker}</td>
                  <td className="px-6 py-4">{h.shares}</td>
                  <td className="px-6 py-4">₹{h.avgCost.toFixed(2)}</td>
                  <td className="px-6 py-4">₹{h.currentPrice.toFixed(2)}</td>
                  <td className={`px-6 py-4 flex items-center ${ret >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                    ₹{Math.abs(ret).toFixed(2)} <span className="text-xs ml-2 opacity-80">({retPct.toFixed(2)}%)</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
