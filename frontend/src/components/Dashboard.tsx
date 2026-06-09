import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { Activity, TrendingUp, TrendingDown, DollarSign } from 'lucide-react';

interface PriceData {
  time: string;
  price: number;
}

export default function Dashboard({ user }: { user: any }) {
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [priceHistory, setPriceHistory] = useState<PriceData[]>([]);
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    // Generate some mock history so the chart isn't empty initially
    const initialHistory = Array.from({ length: 20 }, (_, i) => ({
      time: new Date(Date.now() - (20 - i) * 60000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      price: 2450 + Math.random() * 50
    }));
    setPriceHistory(initialHistory);
    setLivePrice(initialHistory[19].price);

    const ws = new WebSocket(`ws://localhost:8001/ws/${user.id}`);

    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.event === 'price_update' && msg.data.ticker === 'RELIANCE.NS') {
        const newPrice = msg.data.price;
        setLivePrice(newPrice);
        setPriceHistory(prev => {
          const newPoint = { time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), price: newPrice };
          return [...prev.slice(1), newPoint]; // Keep last 20 points
        });
      }
    };

    return () => ws.close();
  }, []);

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
        {/* Ticker Card */}
        <div className="rounded-xl border bg-card text-card-foreground shadow p-6 flex flex-col justify-between hover:border-primary/50 transition-colors cursor-pointer">
          <div className="flex flex-row items-center justify-between space-y-0 pb-2">
            <h3 className="tracking-tight text-sm font-medium">RELIANCE.NS</h3>
            <Activity className="h-4 w-4 text-primary" />
          </div>
          <div>
            <div className="text-2xl font-bold">₹{livePrice ? livePrice.toFixed(2) : '---'}</div>
            <p className="text-xs text-green-500 flex items-center mt-1">
              <TrendingUp className="h-3 w-3 mr-1" /> +1.2% from open
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
      </div>

      {/* Chart Section */}
      <div className="rounded-xl border bg-card text-card-foreground shadow p-6">
        <div className="flex flex-col space-y-1.5 pb-4">
          <h3 className="font-semibold leading-none tracking-tight">RELIANCE.NS Live Price</h3>
          <p className="text-sm text-muted-foreground">Real-time tick data streamed via WebSockets.</p>
        </div>
        <div className="h-[400px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={priceHistory} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
              <XAxis dataKey="time" stroke="#888" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="#888" fontSize={12} tickLine={false} axisLine={false} domain={['auto', 'auto']} tickFormatter={(value) => `₹${value}`} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1a1b1e', border: '1px solid #333', borderRadius: '8px' }}
                itemStyle={{ color: '#fff' }}
              />
              <Line 
                type="monotone" 
                dataKey="price" 
                stroke="hsl(var(--primary))" 
                strokeWidth={3}
                dot={false}
                activeDot={{ r: 6, fill: "hsl(var(--primary))", stroke: "#000", strokeWidth: 2 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
