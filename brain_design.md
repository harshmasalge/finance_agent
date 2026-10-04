# FinSight AI — Agentic Brain Design

> **Status:** Finalised — ready for implementation planning
> **Scope:** All 6 agents, 2 ML models, LLM assignments, memory system, self-evaluation loop, tool registry

---

## Table of Contents

1. [Design Decisions Summary](#1-design-decisions-summary)
2. [Agent Roster](#2-agent-roster)
3. [LLM Assignment Strategy](#3-llm-assignment-strategy)
4. [Tool Registry](#4-tool-registry)
5. [ML Models](#5-ml-models)
6. [Agent Memory System](#6-agent-memory-system)
7. [Self-Evaluation Loop](#7-self-evaluation-loop)
8. [Stock Universe](#8-stock-universe)
9. [Screener Pipeline](#9-screener-pipeline)
10. [Disaster Auto-Execution Logic](#10-disaster-auto-execution-logic)
11. [Complete Data Flow — Brain](#11-complete-data-flow--brain)
12. [LangGraph Node Map](#12-langgraph-node-map)

---

## 1. Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent behaviour | Context-aware — clarify / answer / show work, agent decides | Most natural for real users |
| Monitor autonomy | Suggest action normally, auto-execute on disaster conditions | Balances safety with urgency |
| Memory | Agent's own signal track record only — no user profiling | Self-improvement without privacy risk |
| Signal correctness | Relative to NIFTY50 performance in same window | How real fund managers measure alpha |
| Evaluation windows | 1 day, 7 days, 30 days — all three tracked simultaneously | Covers short-term, swing, positional |
| Agent topology | Orchestrator + 4 reactive sub-agents + 1 screener + 1 self-evaluator | Right tool for each job |
| LLM strategy | Tiered — expensive for reasoning, free for batch/lightweight | Cost efficiency, all free-tier |
| ML models | XGBoost (classifier) + Prophet (trend) — LSTM dropped | Best effort-to-value ratio |
| ML self-evaluation | Yes — XGBoost and Prophet predictions graded same as LLM signals | Complete feedback loop |
| Stock universe | NIFTY 500 — large, mid, and small cap | Best opportunity discovery for retail |
| Screener approach | Quant pre-filter (500 → 20–30) then LLM on shortlist only | Respects rate limits, cost-efficient |

---

## 2. Agent Roster

### Agent 1 — Orchestrator

The entry point for every user query. Reads the question, classifies intent, decides which sub-agents to call and in what mode (parallel or sequential), waits for results, and hands off to LLM synthesis.

**Three response modes the orchestrator chooses between:**
- **Direct answer** — query is clear, context already in working memory → skip clarification, run sub-agents immediately
- **Clarify first** — ambiguous query or missing critical context (e.g. "what should I do?" with no ticker mentioned) → ask one targeted clarifying question before proceeding
- **Show work** — complex multi-factor query or user explicitly asks for full analysis → run all sub-agents, stream intermediate results to UI as they arrive

**Runs on:** Gemini 2.5 Flash (Google AI Studio, free)
**Triggers:** Every user query via `/agent/chat` endpoint
**Does NOT:** Call any data tools directly. Pure routing, planning, mode selection.
**LangGraph node type:** Conditional routing node

---

### Agent 2 — Research Agent

Deep single-stock analysis. Pulls fundamentals, technicals, price history, runs XGBoost classifier and Prophet trend model, and synthesises into a structured stock health report. Also handles head-to-head comparison — orchestrator calls Research Agent twice in parallel for "TCS vs Infosys" queries.

**Runs on:** Gemini 2.5 Flash
**Tools:** `fetch_price_data`, `get_fundamentals`, `get_technical_indicators`, `run_xgboost`, `run_prophet`
**Output schema:**
```json
{
  "ticker": "INFY.NS",
  "signal": "BUY|SELL|HOLD",
  "confidence": 0.74,
  "technical_summary": "...",
  "fundamental_summary": "...",
  "xgboost_signal": "BUY",
  "xgboost_confidence": 0.68,
  "prophet_trend": "UPTREND|DOWNTREND|SIDEWAYS",
  "past_accuracy_context": "..."
}
```

---

### Agent 3 — Sentiment Agent

Owns all news, social media, and market mood signals. Queries pre-computed sentiment scores from PostgreSQL, interprets score direction and velocity, and identifies which specific events are driving sentiment. Lightweight — FinBERT already scored everything, this agent just interprets.

**Runs on:** Llama 3.3 70B via Groq (free)
**Tools:** `get_sentiment_score`, `get_sentiment_trend`, `get_recent_headlines`
**Output schema:**
```json
{
  "ticker": "INFY.NS",
  "current_score": -0.34,
  "trend": "FALLING|RISING|STABLE",
  "velocity": -0.18,
  "key_drivers": ["Q3 miss rumours", "CEO departure news"],
  "signal_contribution": "BEARISH|NEUTRAL|BULLISH"
}
```

---

### Agent 4 — Risk Agent

Computes and interprets the risk profile of a position or potential trade. For BUY queries, runs a "what-if" — what does adding this stock do to overall portfolio risk and concentration?

**Runs on:** Llama 3.3 70B via Groq (free)
**Tools:** `get_portfolio_position`, `compute_var`, `compute_beta`, `compute_volatility`, `get_portfolio_risk_summary`
**Output schema:**
```json
{
  "ticker": "INFY.NS",
  "portfolio_var_current": 0.082,
  "portfolio_var_if_added": 0.094,
  "beta_vs_nifty": 1.12,
  "volatility_30d": 0.034,
  "concentration_current_pct": 18.4,
  "concentration_if_added_pct": 24.1,
  "max_drawdown_30d": -0.067,
  "risk_verdict": "ACCEPTABLE|CAUTION|REJECT"
}
```

---

### Agent 5 — Screener Agent

Opportunity hunter. Scans NIFTY 500 daily to surface stocks not in the user's portfolio that meet multi-factor criteria. Results stored in `screener_results` table and shown in UI as "Today's Picks."

**Runs on:** Llama 3.3 70B via Cerebras (free, 1M tokens/day — needed for bulk)
**Tools:** `get_nifty500_tickers`, `get_technical_indicators`, `get_fundamentals`, `get_sentiment_score`, `screen_stocks`
**Triggers:** Celery Beat — daily at 08:45 IST (before market open). Intraday shortlist re-scan every 2 hours.
**Two-stage pipeline:** See Section 9.

---

### Agent 6 — Self-Evaluation Agent

Runs completely separately from user-facing agents. Grades past signals (both LLM and ML) against actual NIFTY500-relative performance. Writes outcomes back to `signal_log`. Computes aggregated accuracy patterns and stores them in ChromaDB so Research Agent can retrieve historical accuracy context when generating new signals.

**Runs on:** Llama 3.3 70B via Groq (free)
**Tools:** `get_matured_signals`, `fetch_price_data`, `fetch_nifty_price`, `compute_relative_performance`, `update_signal_outcome`, `update_agent_performance`, `write_pattern_to_chromadb`
**Triggers:** Celery Beat — daily (1-day outcomes), weekly (7-day outcomes), monthly (30-day outcomes)
**Never triggered by user queries.**

---

## 3. LLM Assignment Strategy

All free tier. No credit card required for any provider.

| Task | Model | Provider | Free limit |
|------|-------|----------|-----------|
| Orchestrator planning | Gemini 2.5 Flash | Google AI Studio | 1,500 req/day, 10 RPM |
| Research agent reasoning | Gemini 2.5 Flash | Google AI Studio | shared pool |
| Final LLM synthesis | Gemini 2.5 Flash | Google AI Studio | shared pool |
| Sentiment interpretation | Llama 3.3 70B | Groq | ~14,400 req/day free |
| Risk interpretation | Llama 3.3 70B | Groq | shared pool |
| Screener bulk analysis | Llama 3.3 70B | Cerebras | 1M tokens/day |
| Self-evaluation analysis | Llama 3.3 70B | Groq | shared pool |
| Memory summarisation | Gemini 2.5 Flash-Lite | Google AI Studio | 15 RPM |
| Monitor alert generation | Llama 3.3 70B | Groq | shared pool |

**Config-driven model assignment** — no model names hardcoded anywhere:
```
ORCHESTRATOR_MODEL = "gemini-2.5-flash"
REASONING_MODEL = "gemini-2.5-flash"
SYNTHESIS_MODEL = "gemini-2.5-flash"
LIGHTWEIGHT_MODEL = "llama-3.3-70b-versatile"   # Groq
BULK_MODEL = "llama-3.3-70b"                     # Cerebras
MEMORY_MODEL = "gemini-2.5-flash-lite"
```

**Upgrade path:** When free tiers run out, Gemini 2.0 Flash at $0.075/M input tokens is the cheapest paid option — roughly 13× cheaper than Claude Haiku and 2× cheaper than GPT-4o-mini.

**Rate limit strategy:**
- Gemini free tier: 10 RPM, 1,500 RPD. At peak, 1 user query = ~4 Gemini calls. Safe for up to ~375 queries/day or ~6 concurrent users.
- Groq: generous free limits. All lightweight agent calls route here.
- Cerebras: 1M tokens/day dedicated to Screener bulk scanning — never competes with user-facing calls.

---

## 4. Tool Registry

Every tool the agents can call. Each tool is a Python function wrapped for LangGraph.

### Price & market data tools
| Tool | Agent(s) | What it does | Data source |
|------|---------|-------------|-------------|
| `fetch_price_data(ticker, period, interval)` | Research, Self-Eval | OHLCV history | TimescaleDB |
| `fetch_nifty_price(date_range)` | Self-Eval | NIFTY50 index prices for relative comparison | TimescaleDB |
| `get_technical_indicators(ticker)` | Research, Screener | RSI, MACD, Bollinger, MA20/50/200, volume ratio | Computed from TimescaleDB |
| `get_fundamentals(ticker)` | Research, Screener | P/E, EPS, revenue growth, debt-to-equity, sector | PostgreSQL fundamentals table |

### Portfolio tools
| Tool | Agent(s) | What it does | Data source |
|------|---------|-------------|-------------|
| `get_portfolio_position(user_id, ticker)` | Research, Risk | Holdings, avg cost, unrealised P&L, sl_pct, tg_pct | PostgreSQL portfolio table |
| `get_portfolio_risk_summary(user_id)` | Risk | Total VaR, concentration by stock and sector | Computed from PostgreSQL |
| `compute_var(user_id, new_ticker?, new_qty?)` | Risk | Value at Risk — current or hypothetical | Computed |
| `compute_beta(ticker)` | Risk | Beta vs NIFTY50 (60-day rolling) | Computed from TimescaleDB |
| `compute_volatility(ticker)` | Risk | 30-day realised volatility | Computed from TimescaleDB |

### Sentiment tools
| Tool | Agent(s) | What it does | Data source |
|------|---------|-------------|-------------|
| `get_sentiment_score(ticker)` | Sentiment, Screener | Latest aggregated sentiment score (-1 to +1) | PostgreSQL sentiment_scores |
| `get_sentiment_trend(ticker, hours)` | Sentiment | Score history over last N hours, velocity | PostgreSQL sentiment_scores |
| `get_recent_headlines(ticker, limit)` | Sentiment | Last N news headlines mentioning ticker | PostgreSQL sentiment_scores |

### ML model tools
| Tool | Agent(s) | What it does |
|------|---------|-------------|
| `run_xgboost(ticker)` | Research | BUY/SELL/HOLD probability distribution from trained XGBoost model |
| `run_prophet(ticker)` | Research | Trend direction (UPTREND/DOWNTREND/SIDEWAYS) + forecast horizon |

### Screener tools
| Tool | Agent(s) | What it does | Data source |
|------|---------|-------------|-------------|
| `get_nifty500_tickers()` | Screener | Full list of NIFTY 500 constituent tickers | PostgreSQL static table |
| `screen_stocks(criteria)` | Screener | Apply multi-factor quant filter, return shortlist | TimescaleDB + PostgreSQL |

### Self-evaluation tools
| Tool | Agent(s) | What it does |
|------|---------|-------------|
| `get_matured_signals(window_days)` | Self-Eval | All signals in signal_log where outcome is PENDING and created_at <= now - window |
| `compute_relative_performance(ticker, start_date, end_date)` | Self-Eval | Stock return vs NIFTY50 return in same window |
| `update_signal_outcome(signal_id, outcome, outcome_price)` | Self-Eval | Write CORRECT/INCORRECT back to signal_log |
| `update_agent_performance(signal_type, sector, outcome)` | Self-Eval | Update aggregated accuracy stats in agent_performance table |
| `write_pattern_to_chromadb(pattern_text, metadata)` | Self-Eval | Embed and store accuracy pattern for RAG retrieval |

### RAG tool
| Tool | Agent(s) | What it does |
|------|---------|-------------|
| `rag_search(query, scope)` | Research, Orchestrator | Top-5 cosine similarity search in ChromaDB. Scope: "global" (filings, research) or "performance" (agent accuracy patterns) |

---

## 5. ML Models

### XGBoost Classifier

**Purpose:** Classify current market conditions for a stock as BUY / SELL / HOLD signal.

**Features (inputs):**
- RSI (14-period)
- MACD histogram value
- Price vs 20-day MA (% deviation)
- Price vs 200-day MA (% deviation)
- Volume ratio (today vs 20-day average)
- Sentiment score (latest)
- Sentiment velocity (last 4 hours)
- Beta vs NIFTY50
- Sector momentum (sector index 5-day return)
- Broad market regime (NIFTY50 5-day return)

**Label (training target):** 7-day forward return relative to NIFTY50.
- CORRECT (outperformed NIFTY by >1%) → BUY
- UNDERPERFORMED (underperformed NIFTY by >1%) → SELL
- NEUTRAL (within ±1% of NIFTY) → HOLD

**Training data:** Historical OHLCV from TimescaleDB + sentiment history + NIFTY50 baseline. Initial training: 3 years of data across NIFTY 500 universe.

**Retraining trigger:** Once 200+ labelled outcomes exist in `signal_log` where `source = "xgboost"`, a Celery task retrains on this enriched dataset — the model learns from its own prediction history. Retraining runs monthly.

**Output to agent:** Probability distribution `{BUY: 0.68, SELL: 0.18, HOLD: 0.14}` + top 3 feature importances for explainability.

---

### Facebook Prophet (Trend model)

**Purpose:** Decompose price series into trend + seasonality, return directional forecast.

**Why Prophet, not LSTM:**
- Fits fresh on each call — no pre-training needed
- Handles NSE-specific seasonality (budget season, quarterly results cycles, FII flow patterns)
- Output is interpretable — trend direction, confidence interval, seasonality components
- Works well on 2–3 years of daily data which is what yfinance reliably provides

**Inputs:** 2 years of daily OHLCV from TimescaleDB.

**Output to agent:** `{trend: "UPTREND", strength: 0.72, forecast_7d: 2340.0, confidence_interval: [2280, 2400], seasonal_note: "Q4 typically bullish for IT sector"}`

**Self-evaluation:** Prophet's directional prediction (UPTREND/DOWNTREND/SIDEWAYS) is logged to `signal_log` with `source = "prophet"`. Self-Eval Agent checks at 7 and 30 days whether the predicted direction was correct relative to NIFTY50.

---

## 6. Agent Memory System

Only one memory tier — the agent's own track record. No user profiling.

### What is stored

Every signal generated by any agent or ML model is written to `signal_log`:

```
signal_log row:
  id, user_id, ticker
  signal (BUY/SELL/HOLD)
  source (llm_research / xgboost / prophet / monitor)
  confidence (float)
  rationale (text — why this signal was generated)
  price_at_signal
  nifty_price_at_signal (for relative comparison)
  market_conditions (JSON — RSI, sentiment, VaR at signal time)
  outcome (PENDING → CORRECT / INCORRECT)
  outcome_price_1d, outcome_nifty_1d
  outcome_price_7d, outcome_nifty_7d
  outcome_price_30d, outcome_nifty_30d
  outcome_checked_at
  created_at
```

### How it feeds back into reasoning

Self-Eval Agent writes accuracy patterns to ChromaDB in natural language:

```
"XGBoost BUY signals in IT sector during high-VIX market regime 
 (VIX > 18) have 38% accuracy at 7-day window vs NIFTY. 
 Confidence: 47 signals evaluated."

"Sentiment crash alerts (score drop > 0.4 in 2hrs) for banking 
 sector stocks have 81% accuracy — strongest alert type."

"Prophet UPTREND signals on small-cap stocks have only 52% 
 directional accuracy at 30-day window. Low reliability."
```

Research Agent calls `rag_search(query, scope="performance")` before generating any signal, retrieves relevant patterns, and injects them into its reasoning:

> "Note: Based on 47 past evaluations, XGBoost BUY signals in high-volatility markets have only 38% accuracy. Downweighting this signal today."

---

## 7. Self-Evaluation Loop

### Schedule

| Celery task | When it runs | What it evaluates |
|-------------|-------------|------------------|
| `evaluate_1d_outcomes` | Every day at 16:00 IST | Signals created 1 trading day ago |
| `evaluate_7d_outcomes` | Every Monday at 08:00 IST | Signals created 7 days ago |
| `evaluate_30d_outcomes` | 1st of every month at 08:00 IST | Signals created 30 days ago |

### Evaluation logic

For each matured signal:

```
1. Fetch stock price at signal date (from TimescaleDB)
2. Fetch stock price at evaluation date (from TimescaleDB)
3. Fetch NIFTY50 price at both dates
4. Compute:
   stock_return = (price_now - price_then) / price_then
   nifty_return = (nifty_now - nifty_then) / nifty_then
   alpha = stock_return - nifty_return

5. For BUY signal:
   CORRECT   if alpha > +0.01 (outperformed NIFTY by >1%)
   INCORRECT if alpha < -0.01 (underperformed NIFTY by >1%)
   NEUTRAL   if -0.01 <= alpha <= 0.01

6. For SELL signal (inverse):
   CORRECT   if alpha < -0.01 (stock fell more than NIFTY)
   INCORRECT if alpha > +0.01

7. Write outcome + prices back to signal_log
8. Update agent_performance table:
   (source, signal_type, sector, market_regime) → accuracy_rate
9. If enough data (>50 signals for this combination):
   Write/update pattern in ChromaDB
```

### XGBoost retraining trigger

Monthly Celery task checks: `SELECT COUNT(*) FROM signal_log WHERE source = 'xgboost' AND outcome != 'PENDING'`. If >= 200, triggers model retraining using signal_log outcomes as labels. New model replaces old one. Training takes <2 minutes on CPU with 200–2000 samples.

---

## 8. Stock Universe

**NIFTY 500** — covers:
- NIFTY 100 (large-cap): top 100 stocks by market cap
- NIFTY Midcap 150: stocks ranked 101–250
- NIFTY Smallcap 250: stocks ranked 251–500

**Stored in:** PostgreSQL table `nifty500_constituents` — ticker, company name, sector, index membership, market cap tier. Updated quarterly via NSE website scrape.

**Why NIFTY 500 and not full NSE (~2,000 stocks):**
- Free data quality is reliable for NIFTY 500 (sufficient trading volume, yfinance coverage)
- Below NIFTY 500, many stocks have gaps, low liquidity, and unreliable price data
- NIFTY 500 still covers 93%+ of total NSE market capitalisation — true opportunity discovery

---

## 9. Screener Pipeline

Two-stage design to respect LLM API rate limits.

### Stage 1 — Quantitative pre-filter (no LLM, pure Python, runs in <30 seconds)

Applied to all 500 stocks using data from TimescaleDB and PostgreSQL. Filter criteria:

| Filter | Condition | Purpose |
|--------|-----------|---------|
| Liquidity | Avg daily volume (20-day) > 50,000 shares | Removes illiquid stocks |
| RSI range | 30 < RSI < 70 | Not already overbought or oversold |
| Trend confirmation | Price > 50-day MA | Basic uptrend filter |
| Volume interest | Today's volume > 1.5× 20-day average | Signs of activity |
| Valuation | P/E < 1.5× sector median | Not grossly overvalued |
| Not already held | Ticker not in user's current portfolio | Only new opportunities |
| Sentiment floor | Sentiment score > -0.3 | Avoid stocks with strongly negative news |

**Typical output:** 20–35 stocks from 500.

### Stage 2 — LLM qualitative analysis (on shortlist only)

Screener Agent calls Research Agent (lightweight mode) and Sentiment Agent for each shortlisted stock. At 10 RPM Gemini free tier, 30 stocks = ~3 minutes. Runs comfortably before market open.

**Final output:** Top 5 ranked by composite score (technical + fundamental + sentiment + past accuracy context from ChromaDB).

### Schedule
- Full 500-stock quant scan: 08:45 IST daily
- LLM qualitative analysis on shortlist: 09:00–09:10 IST
- Results in `screener_results` table by 09:12 IST — ready for market open at 09:15 IST
- Intraday shortlist refresh: every 2 hours during market hours (quant filter only, no LLM re-call)

---

## 10. Disaster Auto-Execution Logic

Normal mode: proactive monitor generates alert + suggestion. User decides.

Disaster auto-execution triggers when ALL of the following are true simultaneously:

| Condition | Threshold |
|-----------|-----------|
| P&L loss from buy price | > -15% |
| Sentiment score | < -0.6 (strongly negative) |
| RSI | < 28 (deeply oversold) |
| Volume spike | > 5× 20-day average (panic selling signal) |

When all 4 conditions fire simultaneously → agent automatically executes a SELL paper trade for the full position, then sends an alert:

```
"AUTO-EXECUTED: Sold 100% of TATASTEEL position.
 Triggered by simultaneous: -17.2% loss, sentiment -0.71,
 RSI 24, volume 6.8× average. This met all 4 disaster
 criteria. Trade logged. You can review and manually
 reverse this in Portfolio."
```

User can reverse the auto-execution manually in the Portfolio UI within 24 hours. After 24 hours, the trade is considered confirmed.

This logic lives in `portfolio_monitor.py` (Celery task), not in LangGraph.

---

## 11. Complete Data Flow — Brain

```
USER QUERY
    │
    ▼
POST /agent/chat
  {message, conversation_history}
    │
    ▼ (load from Redis)
Working memory — session state
    │
    ▼ (load from PostgreSQL)
Signal track record context (recent accuracy stats)
    │
    ▼
ORCHESTRATOR (Gemini 2.5 Flash)
  Classify intent → select mode → plan sub-agent calls
    │
    ├─────────────────────┬───────────────────┐
    ▼                     ▼                   ▼
RESEARCH AGENT      SENTIMENT AGENT      RISK AGENT
(Gemini 2.5 Flash)  (Llama 3.3 70B)     (Llama 3.3 70B)
  │                     │                   │
  ├─ fetch_price_data    ├─ get_sentiment     ├─ get_portfolio
  ├─ get_fundamentals    ├─ get_trend         ├─ compute_var
  ├─ get_technicals      └─ get_headlines     ├─ compute_beta
  ├─ run_xgboost                              └─ compute_vol
  ├─ run_prophet
  └─ rag_search
       (accuracy patterns from Self-Eval)
    │                     │                   │
    └─────────────────────┴───────────────────┘
                          │ (all results merged)
                          ▼
              LLM SYNTHESIS (Gemini 2.5 Flash)
              Generate structured response
                          │
                          ▼
              LOG TO signal_log
              (ticker, signal, confidence, rationale,
               source=llm, market_conditions)
                          │
                          ▼
              RETURN structured response
              {response, signal, confidence, sources_used}
                          │
                          ▼
              WebSocket → React UI

---

PARALLEL BACKGROUND TRACKS (no user needed)

DAILY 08:45 IST:
  Screener Agent → quant filter 500 stocks → LLM on 20-30
  → screener_results table → "Today's Picks" UI widget

EVERY 15 MIN (market hours):
  Monitor Agent → check all portfolios → alert thresholds
  → AlertLog → WebSocket → user alert card

  If disaster conditions (all 4 met):
  → Auto-execute paper SELL → alert with AUTO-EXECUTED flag

DAILY 16:00 IST:
  Self-Eval → grade 1-day signals vs NIFTY
  → update signal_log outcomes
  → update agent_performance table
  → write patterns to ChromaDB

WEEKLY MONDAY 08:00 IST:
  Self-Eval → grade 7-day signals → same pipeline

MONTHLY 1st 08:00 IST:
  Self-Eval → grade 30-day signals → same pipeline
  If XGBoost signal count >= 200 → retrain XGBoost
```

---

## 12. LangGraph Node Map

```
StateGraph nodes:
  ├─ entry_node          — load working memory, inject signal context
  ├─ orchestrator_node   — classify intent, plan, route
  ├─ research_node       — ReAct loop with research tools
  ├─ sentiment_node      — ReAct loop with sentiment tools
  ├─ risk_node           — ReAct loop with risk tools
  ├─ synthesis_node      — merge all outputs, generate response
  ├─ signal_log_node     — write signal to PostgreSQL
  └─ memory_update_node  — update Redis session state

Edges:
  entry_node → orchestrator_node
  orchestrator_node → [research_node, sentiment_node, risk_node]  (parallel)
  research_node → synthesis_node
  sentiment_node → synthesis_node
  risk_node → synthesis_node
  synthesis_node → signal_log_node
  signal_log_node → memory_update_node
  memory_update_node → END

Conditional edges (orchestrator):
  if intent == "clarify_needed" → clarify_node → END
  if intent == "portfolio_only" → skip research, run risk only
  if intent == "sentiment_only" → skip research + risk, run sentiment only
  if intent == "comparison"     → run research_node × 2 in parallel

State object (persisted in Redis):
  {
    user_id, session_id,
    messages: [...],          # conversation history
    current_task,             # what orchestrator is doing
    research_output,
    sentiment_output,
    risk_output,
    synthesis_output,
    signal_accuracy_context,  # retrieved from ChromaDB at session start
    iteration_count           # ReAct loop counter per node
  }
```

---

*Brain design version 1.0 — finalised.*
*Next step: brain implementation plan for vibe coding agent.*
