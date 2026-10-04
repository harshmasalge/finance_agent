export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8001';
export const WS_URL = API_URL.replace(/^http/, 'ws');

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

// ---------- Domain types ----------
export interface User { id: number; email: string; name: string; picture: string; balance: number; }

export interface Holding {
  ticker: string; quantity: number; avg_cost: number; current_price: number; current_value: number;
  unrealised_pnl: number; unrealised_pnl_pct: number; sl_pct: number | null; tg_pct: number | null;
}

export interface Trade {
  id: number; ticker: string; side: 'BUY' | 'SELL'; quantity: number; fill_price: number;
  timestamp: string; virtual_balance_after: number;
}

export interface AlertItem {
  id: number; ticker: string; alert_type: string; message: string; signal: string;
  is_read: boolean; created_at: string; price_at_alert?: number;
}

export interface HistoryPoint { time: string; TotalValue: number; [ticker: string]: number | string; }

// ---------- Advisor types (mirror backend/agent/schemas.py) ----------
export interface Claim { text: string; citations: string[]; }
export interface Section { title: string; claims: Claim[]; }
export interface FinalAnswer {
  answer_type: 'stock_analysis' | 'comparison' | 'portfolio_health' | 'ideas' | 'sentiment' | 'general';
  headline: string;
  verdict: 'BUY' | 'SELL' | 'HOLD' | null;
  verdict_ticker: string | null;
  confidence: number | null;
  sections: Section[];
  data_gaps: string[];
}
export interface Evidence {
  id: string; agent: string; tool: string; input: Record<string, unknown>; output: unknown; created_at: string;
}
export interface Validation {
  status: 'passed' | 'warning' | 'revising' | 'skipped';
  issues: string[]; claims?: number; cited_claims?: number; evidence_items?: number; attempts?: number;
}
export interface ScoreFactor { name: string; label: string; score: number; weight: number; reason: string; evidence_id: string | null; }
export interface Scorecard {
  ticker: string; score: number; verdict: 'BUY' | 'SELL' | 'HOLD'; confidence: number; evidence_id?: string;
  thresholds: { buy: number; sell: number }; factors: ScoreFactor[]; missing: string[]; coverage: number;
}
export interface ToolCall { id: string; tool: string; input: Record<string, unknown>; }
export interface Step { node: string; label: string; status: 'running' | 'done'; detail?: string; tools?: ToolCall[]; }
export interface AnswerPayload {
  answer: FinalAnswer; evidence: Evidence[]; validation: Validation | null; scorecards?: Scorecard[]; intent?: string;
  tickers?: string[]; steps?: Step[]; duration_s?: number;
}
export interface ChatMessage {
  id: number | string; role: 'user' | 'assistant'; content: string; payload?: AnswerPayload | null; created_at?: string;
}
export interface ChatSummary { id: number; title: string; created_at: string | null; updated_at: string | null; }
