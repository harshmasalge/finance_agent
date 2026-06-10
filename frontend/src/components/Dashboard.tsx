import { useEffect, useState, useRef } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, Brush } from 'recharts';
import { Activity, TrendingUp, TrendingDown, DollarSign, Briefcase } from 'lucide-react';

interface Holding {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price?: number;
}

interface PriceData {
  time: string;
  [key: string]: number | string;
}

const stringToColor = (str: string) => {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash % 360);
  return `hsl(${hue}, 70%, 50%)`;
};

export default function Dashboard({ user }: { user: any }) {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [priceHistory, setPriceHistory] = useState<PriceData[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastTotalValue, setLastTotalValue] = useState<number | null>(null);
  
  const livePricesRef = useRef<Record<string, number>>({});

  useEffect(() => {
    // 1. Fetch historical portfolio reconstruction
    fetch('http://localhost:8001/portfolio/history', { credentials: 'include' })
      .then(res => res.ok ? res.json() : [])
      .then(historyData => {
        setPriceHistory(historyData);
        if (historyData.length > 0) {
          setLastTotalValue(historyData[historyData.length - 1].TotalValue);
        }
      })
      .catch(console.error);

    // 2. Fetch current holdings
    fetch('http://localhost:8001/portfolio/holdings', { credentials: 'include' })
      .then(res => res.ok ? res.json() : [])
      .then(data => {
        setHoldings(data);
        const initialPrices: Record<string, number> = {};
        data.forEach((h: Holding) => {
          if (h.current_price) {
            initialPrices[h.ticker] = h.current_price;
          } else {
            initialPrices[h.ticker] = h.avg_cost;
          }
        });
        livePricesRef.current = { ...livePricesRef.current, ...initialPrices };
        setLivePrices({ ...livePricesRef.current });
      })
      .catch(console.error);

    const ws = new WebSocket(`ws://localhost:8001/ws/${user.id}`);

    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.event === 'price_update') {
        const { ticker, price } = msg.data;
        livePricesRef.current = { ...livePricesRef.current, [ticker]: price };
        setLivePrices({ ...livePricesRef.current });
      }
    };

    // Append to chart history every 3 seconds (Only if market is open)
    const interval = setInterval(() => {
      // Market hours check (9:15 to 15:30 IST)
      const now = new Date();
      const isWeekday = now.getDay() >= 1 && now.getDay() <= 5;
      const hours = now.getHours();
      const mins = now.getMinutes();
      const time = hours * 100 + mins;
      const isMarketOpen = isWeekday && time >= 915 && time <= 1530;

      if (!isMarketOpen) return; // Do not append flat lines when market is closed

      setHoldings(currentHoldings => {
        if (currentHoldings.length === 0) return currentHoldings;
        
        const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const newPoint: PriceData = { time: timeStr };
        
        let hasData = false;
        let currentAssetValue = 0;
        
        currentHoldings.forEach(h => {
          const lp = livePricesRef.current[h.ticker];
          if (lp && h.avg_cost > 0) {
            newPoint[h.ticker] = Number((((lp - h.avg_cost) / h.avg_cost) * 100).toFixed(2));
            currentAssetValue += (lp * h.quantity);
            hasData = true;
          }
        });

        if (hasData) {
          // Append TotalValue line representing cash + stock value
          newPoint["TotalValue"] = Number((user.balance + currentAssetValue).toFixed(2));
          
          setPriceHistory(prev => {
            const next = [...prev, newPoint];
            if (next.length > 2000) next.shift(); // keep decent history
            return next;
          });
        }
        
        return currentHoldings;
      });
    }, 60000); // 60s interval instead of 3s so the chart timeline isn't spammed while market is open

    return () => {
      ws.close();
      clearInterval(interval);
    };
  }, [user.id]);

  // Calculations for summary cards
  const totalInvested = holdings.reduce((sum, h) => sum + (h.quantity * h.avg_cost), 0);
  const totalValue = holdings.reduce((sum, h) => sum + (h.quantity * (livePrices[h.ticker] || h.avg_cost)), 0);
  const totalReturn = totalValue - totalInvested;
  const returnPct = totalInvested > 0 ? (totalReturn / totalInvested) * 100 : 0;

  return (
    <div className="p-6 space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight">Market Overview</h1>
        <div className="flex items-center space-x-2">
          <div className={`w-3 h-3 rounded-full ${wsConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
          <span className="text-sm text-muted-foreground">
            {wsConnected ? 'Live Connection Active' : 'Disconnected'}
          </span>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        {/* Portfolio Returns Card */}
        <div className="rounded-xl border bg-card text-card-foreground shadow p-6 flex flex-col justify-between">
          <div className="flex flex-row items-center justify-between space-y-0 pb-2">
            <h3 className="tracking-tight text-sm font-medium">Total Unrealised PnL</h3>
            <Activity className="h-4 w-4 text-primary" />
          </div>
          <div>
            <div className={`text-2xl font-bold ${totalReturn >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              {totalReturn >= 0 ? '+' : ''}₹{totalReturn.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </div>
            <p className={`text-xs flex items-center mt-1 ${totalReturn >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              {totalReturn >= 0 ? <TrendingUp className="h-3 w-3 mr-1" /> : <TrendingDown className="h-3 w-3 mr-1" />} 
              {returnPct.toFixed(2)}% ROI
            </p>
          </div>
        </div>
        
        {/* Mock Portfolio Card */}
        <div className="rounded-xl border bg-card text-card-foreground shadow p-6 flex flex-col justify-between">
          <div className="flex flex-row items-center justify-between space-y-0 pb-2">
            <h3 className="tracking-tight text-sm font-medium">Virtual Balance</h3>
            <DollarSign className="h-4 w-4 text-primary" />
          </div>
          <div>
            <div className="text-2xl font-bold">₹{user.balance.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</div>
            <p className="text-xs text-muted-foreground flex items-center mt-1">
              Available cash for trading
            </p>
          </div>
        </div>
        
        {/* Active Holdings Count */}
        <div className="rounded-xl border bg-card text-card-foreground shadow p-6 flex flex-col justify-between">
          <div className="flex flex-row items-center justify-between space-y-0 pb-2">
            <h3 className="tracking-tight text-sm font-medium">Active Holdings</h3>
            <Briefcase className="h-4 w-4 text-primary" />
          </div>
          <div>
            <div className="text-2xl font-bold">{holdings.length} Positions</div>
            <p className="text-xs text-muted-foreground mt-1">
              Currently tracked in live market
            </p>
          </div>
        </div>
      </div>

      {/* Chart Section */}
      <div className="rounded-xl border bg-card text-card-foreground shadow p-6">
        <div className="flex flex-col space-y-1.5 pb-4">
          <h3 className="font-semibold leading-none tracking-tight">Portfolio Performance (ROI %)</h3>
          <p className="text-sm text-muted-foreground">
            {holdings.length > 0 
              ? "Live tracking of your holdings' return on investment percentage." 
              : "No active holdings. Execute a trade in the Portfolio tab to see live tracking here."}
          </p>
        </div>
        <div className="h-[400px] w-full">
          {holdings.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={priceHistory} margin={{ top: 5, right: 30, left: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
                <XAxis dataKey="time" stroke="#888" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis yAxisId="left" stroke="#888" fontSize={12} tickLine={false} axisLine={false} domain={['auto', 'auto']} tickFormatter={(value) => `${value}%`} />
                <YAxis yAxisId="right" orientation="right" stroke="#aaa" fontSize={12} tickLine={false} axisLine={false} domain={['auto', 'auto']} tickFormatter={(value) => `₹${value/1000}k`} />
                
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1a1b1e', border: '1px solid #333', borderRadius: '8px' }}
                  itemStyle={{ color: '#fff' }}
                  formatter={(value: number, name: string) => {
                    if (name === "TotalValue") return [`₹${value.toLocaleString('en-IN')}`, 'Portfolio Value'];
                    return [`${value}%`, 'ROI'];
                  }}
                />
                <Legend iconType="circle" />
                
                {/* Individual Holding ROI % lines */}
                {holdings.map(h => (
                  <Line 
                    yAxisId="left"
                    key={h.ticker}
                    type="monotone" 
                    name={h.ticker}
                    dataKey={h.ticker} 
                    stroke={stringToColor(h.ticker)} 
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                ))}
                
                {/* Total Portfolio Value Line */}
                <Line
                  yAxisId="right"
                  type="monotone"
                  name="TotalValue"
                  dataKey="TotalValue"
                  stroke="#ffffff"
                  strokeWidth={3}
                  strokeDasharray="5 5"
                  dot={false}
                  activeDot={{ r: 6 }}
                />
                
                <Brush dataKey="time" height={30} stroke="#333" fill="#1a1b1e" tickFormatter={() => ''} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full flex items-center justify-center border-2 border-dashed border-gray-800 rounded-lg text-muted-foreground">
              Awaiting trades...
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
