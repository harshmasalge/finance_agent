import React, { useState, useEffect } from 'react';
import { Bell, ThumbsUp, ThumbsDown, AlertCircle, TrendingUp, CheckCircle, Clock } from 'lucide-react';

interface Alert {
  id: number;
  ticker: string;
  alert_type: string;
  message: string;
  signal: string;
  is_read: boolean;
  created_at: string;
}

export default function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [voted, setVoted] = useState<Set<number>>(new Set());

  const fetchAlerts = async () => {
    try {
      const res = await fetch('http://localhost:8001/alerts', { credentials: 'include' });
      if (res.ok) {
        setAlerts(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 30000); // refresh every 30s
    return () => clearInterval(interval);
  }, []);

  const markRead = async (id: number) => {
    try {
      await fetch(`http://localhost:8001/alerts/${id}/read`, {
        method: 'PATCH',
        credentials: 'include'
      });
      setAlerts(prev => prev.map(a => a.id === id ? { ...a, is_read: true } : a));
    } catch (e) {
      console.error(e);
    }
  };

  const submitFeedback = async (id: number, isPositive: boolean) => {
    try {
      await fetch(`http://localhost:8001/alerts/${id}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ is_positive: isPositive })
      });
      setVoted(prev => new Set(prev).add(id));
    } catch (e) {
      console.error(e);
    }
  };

  const getAlertIcon = (type: string) => {
    if (type.includes('STOP_LOSS') || type.includes('CRASH')) return <AlertCircle className="text-red-500" />;
    if (type.includes('TARGET') || type.includes('BUY')) return <CheckCircle className="text-green-500" />;
    return <TrendingUp className="text-amber-500" />;
  };

  const getSignalBadge = (signal: string) => {
    const colors: Record<string, string> = {
      'BUY': 'bg-green-500/20 text-green-500',
      'SELL': 'bg-red-500/20 text-red-500',
      'HOLD': 'bg-amber-500/20 text-amber-500',
      'CAUTION': 'bg-amber-500/20 text-amber-500'
    };
    return <span className={`px-2 py-1 text-xs font-bold rounded ${colors[signal] || 'bg-gray-500/20 text-gray-500'}`}>{signal}</span>;
  };

  if (loading) return <div className="p-6">Loading alerts...</div>;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center space-x-3 mb-6">
        <Bell className="h-8 w-8 text-primary" />
        <h1 className="text-3xl font-bold tracking-tight">Alert Center</h1>
      </div>

      <div className="space-y-4">
        {alerts.length === 0 && (
          <div className="text-center py-12 text-muted-foreground border rounded-xl bg-card">
            No recent alerts
          </div>
        )}
        
        {alerts.map((alert) => (
          <div 
            key={alert.id}
            onClick={() => { if (!alert.is_read) markRead(alert.id); }}
            className={`p-4 rounded-xl border flex flex-col md:flex-row gap-4 justify-between transition-colors cursor-pointer ${
              alert.is_read ? 'bg-card opacity-80' : 'bg-primary/5 border-primary/20'
            }`}
          >
            <div className="flex space-x-4">
              <div className="mt-1">{getAlertIcon(alert.alert_type)}</div>
              <div>
                <div className="flex items-center space-x-3 mb-1">
                  <span className="font-bold text-lg">{alert.ticker}</span>
                  {getSignalBadge(alert.signal)}
                  <span className="text-xs text-muted-foreground font-mono bg-muted px-2 py-0.5 rounded">
                    {alert.alert_type}
                  </span>
                </div>
                <p className="text-sm md:text-base">{alert.message}</p>
                <div className="flex items-center space-x-2 mt-2 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  <span>{new Date(alert.created_at).toLocaleString()}</span>
                </div>
              </div>
            </div>

            <div className="flex items-center space-x-2 shrink-0 self-start md:self-center">
              <button 
                disabled={voted.has(alert.id)}
                onClick={(e) => { e.stopPropagation(); submitFeedback(alert.id, true); }}
                className={`p-2 rounded-full border hover:bg-green-500/20 transition-colors ${voted.has(alert.id) ? 'opacity-50 cursor-not-allowed' : ''}`}
                title="Helpful"
              >
                <ThumbsUp className="h-4 w-4" />
              </button>
              <button 
                disabled={voted.has(alert.id)}
                onClick={(e) => { e.stopPropagation(); submitFeedback(alert.id, false); }}
                className={`p-2 rounded-full border hover:bg-red-500/20 transition-colors ${voted.has(alert.id) ? 'opacity-50 cursor-not-allowed' : ''}`}
                title="Not Helpful"
              >
                <ThumbsDown className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
