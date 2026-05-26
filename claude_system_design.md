# Agentic AI Stock Market Advisor — Complete System Design

> **Project:** FinSight AI — An agentic, full-stack AI platform for Indian retail investors
> **Stage:** Ideation → System Design (finalised)
> **Market:** NSE / BSE (Indian equities)
> **Mode:** Paper trading (virtual money, real market data)

---

## Table of Contents

1. [Product Vision](#1-product-vision)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Data Flow 1 — User Request Lifecycle](#3-data-flow-1--user-request-lifecycle)
4. [Data Flow 2 — Market Data Ingestion](#4-data-flow-2--market-data-ingestion)
5. [Data Flow 3 — Agent ReAct Loop](#5-data-flow-3--agent-react-loop)
6. [Data Flow 4 — Paper Trade Execution](#6-data-flow-4--paper-trade-execution)
7. [Data Flow 5 — Sentiment Pipeline](#7-data-flow-5--sentiment-pipeline)
8. [Data Flow 6 — Auth & WebSocket Lifecycle](#8-data-flow-6--auth--websocket-lifecycle)
9. [Proactive Monitor Agent](#9-proactive-monitor-agent)
10. [Agent Memory System](#10-agent-memory-system)
11. [Observability & Evaluation](#11-observability--evaluation)
12. [Indian Market Data Sources](#12-indian-market-data-sources)
13. [Technology Stack](#13-technology-stack)
14. [Alert Trigger Matrix](#14-alert-trigger-matrix)
15. [All Design Decisions](#15-summary--all-design-decisions)

---

## 1. Product Vision

FinSight AI solves a single, well-defined problem: **retail investors in India make emotional, uninformed decisions because they lack the tools to continuously research, track, and evaluate their stock holdings.**

The system provides:

- **Reactive intelligence** — user asks "should I buy more Infosys?" and receives a structured, data-backed recommendation with full rationale.
- **Proactive intelligence** — the system continuously monitors every stock in the user's portfolio and pushes actionable alerts (sell, hold, add) without being asked.
- **Portfolio management** — users add/remove holdings (ticker, quantity, buy price, buy date) and set personal stop-loss and target percentages per stock.
- **Paper trading** — all trades execute with virtual money against real NSE/BSE market prices. No real money, no broker integration, no regulatory complexity.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                             │
│   Dashboard · AI Chat Interface · Portfolio Manager · Alerts        │
└────────────────────────┬────────────────────────────────────────────┘
                         │ HTTP / WebSocket
┌────────────────────────▼────────────────────────────────────────────┐
│                   API GATEWAY (FastAPI)                             │
│         Google OAuth · Session Cookie · REST · WebSocket            │
│                      Celery (task queue)                            │
└──────┬──────────────────────────────────────────────────────┬───────┘
       │                                                      │
┌──────▼──────────────────────────┐   ┌───────────────────────▼──────┐
│   REACTIVE AGENT TRACK          │   │  PROACTIVE MONITOR TRACK      │
│   LangGraph Orchestrator        │   │  Celery Beat (every 15 min)   │
│   ├─ Research Agent             │   │  ├─ Fetch all portfolios       │
│   ├─ Sentiment Agent            │   │  ├─ Per-stock health check     │
│   ├─ Risk Agent                 │   │  ├─ Alert threshold eval       │
│   └─ Portfolio Agent            │   │  └─ Push alerts via WebSocket  │
└──────┬──────────────────────────┘   └───────────────────────┬───────┘
       │                                                       │
┌──────▼───────────────────────────────────────────────────────▼──────┐
│                         AI TOOLS LAYER                              │
│   LLM Engine (GPT-4o / Claude) · ML Models · Vector Store (Chroma) │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│                           DATA LAYER                                │
│  TimescaleDB (OHLCV) · PostgreSQL (users, portfolio, fundamentals)  │
│  Redis (cache, pub/sub, sessions) · ChromaDB (vector embeddings)    │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│                         EXTERNAL DATA                               │
│  yfinance (RELIANCE.NS) · nsetools · Angel One · NewsAPI · Reddit   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow 1 — User Request Lifecycle

Every user query fans out to all four sub-agents in parallel. Results merge and the LLM synthesises a single structured response.

```
User query: "Should I sell my TATASTEEL position?"
        │
        ▼
FastAPI gateway
  JWT/session verify → parse intent → enqueue job
        │
        ▼
LangGraph Orchestrator
  Decompose → plan → assign to sub-agents (parallel)
  ┌──────────┬────────────┬──────────┬──────────────┐
  ▼          ▼            ▼          ▼
Research   Sentiment    Risk       Portfolio
Agent      Agent        Agent      Agent
  │          │            │          │
Fundamental News+social  VaR, beta  P&L, weight
screening  score        volatility  fit
  └──────────┴────────────┴──────────┴──────────────┘
                    │ (merged)
                    ▼
           LLM Synthesis
           Merge · reason · generate recommendation
                    │
                    ▼
           Structured response card
           ┌─────────────────────────────┐
           │ Signal:      HOLD           │
           │ Confidence:  72%            │
           │ RSI:         58 (neutral)   │
           │ Sentiment:  -0.2 (cautious) │
           │ Rationale:  [3 reasons]     │
           │ Risk level:  MEDIUM         │
           └─────────────────────────────┘
```

**Key design decisions:**
- Sub-agents run in parallel via LangGraph parallel nodes, not sequentially.
- Each sub-agent is a separate LangGraph node with its own dedicated tool set.
- The orchestrator can re-route or retry individual sub-agents on failure.
- Response is always structured (not free-text) so the UI renders it as a card.

---

## 4. Data Flow 2 — Market Data Ingestion

Raw data polled on a schedule, normalised, split into three destinations simultaneously.

```
External APIs                  Celery Beat Scheduler
┌────────────┐                ┌───────────────────────────────────┐
│ yfinance   │──────────────► │ Poll every 1 min (market hours)   │
│ RELIANCE.NS│                │ Poll every 1 hr  (off hours)      │
│ TCS.NS ... │                │ Once at 09:15 IST (market open)   │
├────────────┤                │ Once at 15:30 IST (market close)  │
│ nsetools   │──────────────► └──────────────┬────────────────────┘
│ Live quotes│                               │
├────────────┤                               ▼
│ Alpha      │──────────────► Normalisation worker
│ Vantage    │                Clean · validate · unify schema
├────────────┤                Detect anomalies · drop duplicates
│ NewsAPI /  │──────────────►                │
│ Reddit RSS │                ┌──────────────┼──────────────┐
└────────────┘                ▼              ▼              ▼
                         TimescaleDB   PostgreSQL       Redis
                         OHLCV history  Fundamentals    Latest price
                         (permanent)    Metadata        60s TTL
                                                        │
                                                        ▼
                                                   WebSocket pub/sub
                                                   Push live ticks
                                                   to React dashboard
```

**NSE market hours (IST, Asia/Kolkata):**
- High-frequency polling: 09:15–15:30, Mon–Fri
- Off-hours: hourly polling for news/sentiment, daily EOD snapshot
- Public holidays: NSE holiday calendar fetched quarterly, stored in PostgreSQL

**Indian ticker format:**
- NSE stocks: `RELIANCE.NS`, `TCS.NS`, `INFY.NS`
- BSE stocks: `500325.BO`, `532540.BO`
- Indices: `^NSEI` (NIFTY 50), `^BSESN` (SENSEX)

---

## 5. Data Flow 3 — Agent ReAct Loop

The agent cycles Think → Act → Observe until it has sufficient context. This is the internal loop of every sub-agent.

```
Task from orchestrator
        │
        ▼
    ┌─────────────────────────────────────────────┐
    │  THINK                                       │
    │  LLM: "What tool do I need next?"           │
    │  Reviews conversation history + tool results │
    └──────────────────────┬──────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────┐
    │  ACT — call one tool                         │
    │  ├─ fetch_price_data(ticker, period)         │
    │  │    → TimescaleDB query                   │
    │  ├─ get_sentiment_score(ticker)              │
    │  │    → PostgreSQL sentiment table           │
    │  ├─ run_ml_model(ticker, model_type)         │
    │  │    → XGBoost / LSTM / Prophet             │
    │  ├─ rag_search(query)                        │
    │  │    → ChromaDB similarity search           │
    │  ├─ get_fundamentals(ticker)                 │
    │  │    → PostgreSQL fundamentals table        │
    │  └─ get_portfolio_position(user_id, ticker)  │
    │       → PostgreSQL portfolio table           │
    └──────────────────────┬──────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────┐
    │  OBSERVE                                     │
    │  Append tool result to context window        │
    │  LangGraph state updated                     │
    └──────────────────────┬──────────────────────┘
                           │
               ┌───────────┴────────────┐
          Need more?               Have enough?
               │                        │
               └──► THINK again         └──► Return final answer
                    (max 10 iterations)       to orchestrator
```

**Limits:** Max 10 ReAct iterations per sub-agent. If exceeded, agent returns best available answer with a low-confidence flag. LangSmith traces every step.

---

## 6. Data Flow 4 — Paper Trade Execution

Every trade goes through validation → risk check → real price fetch → simulated fill → dual write.

```
User: "BUY 10 shares of INFY"
        │
        ▼
Trade engine validation
  ├─ Sufficient virtual balance?         → FAIL: reject + reason
  ├─ Position size ≤ 20% of portfolio?   → FAIL: reject + reason
  ├─ Valid NSE/BSE ticker?               → FAIL: reject + reason
  └─ Within market hours?                → configurable (warn/block)
        │ (pass)
        ▼
Risk limit check
  ├─ Portfolio VaR gate (max 15% daily VaR)
  ├─ Single-stock concentration (max 30%)
  └─ Sector concentration (max 40%)
        │ (pass)
        ▼
Fetch fill price
  Redis cache → latest NSE price (60s TTL)
  Fallback: yfinance real-time quote if cache stale
        │
        ▼
Simulate fill
  Apply 0.05% slippage (market impact model)
  Deduct (price × qty × 1.0005) from virtual balance
  Add STT + exchange charges (NSE standard rates)
        │
        ├──────────────────────────────┐
        ▼                              ▼
PostgreSQL trade_log           Portfolio state update
  trade_id, user_id             holdings: avg_cost recalculated
  ticker, quantity              unrealised_pnl updated
  fill_price, slippage          portfolio_weight updated
  timestamp                     total_invested updated
  virtual_balance_after
        │
        ▼
WebSocket → trade confirmation card pushed to user
Signal logged to eval store (for backtesting engine)
```

---

## 7. Data Flow 5 — Sentiment Pipeline

Four sources → cleaner → FinBERT scoring → volume-weighted aggregation → per-ticker sentiment score.

```
NewsAPI        Reddit              X / Twitter      RSS Feeds
headlines      r/IndiaInvestments  Cashtags         Moneycontrol
every 15 min   r/IndianStockMarket mentions         Economic Times
               r/DalalStreet
     │               │                  │                │
     └───────────────┴──────────────────┴────────────────┘
                               │
                               ▼
                  Collector + text cleaner
                  ├─ Deduplicate (URL + content hash)
                  ├─ Strip HTML, extract plain text
                  ├─ Extract ticker mentions
                  ├─ Filter: must mention a tracked ticker
                  └─ Language: keep English + Hindi (transliterate)
                               │
                               ▼
                  NLP sentiment scoring
                  ├─ Primary:  FinBERT (finance-tuned BERT)
                  │            Score: -1.0 to +1.0
                  └─ Fallback: VADER
                               │
                               ▼
                  Score aggregation per ticker
                  ├─ Volume-weighted (more articles = more weight)
                  ├─ Recency decay (exponential, half-life: 4 hours)
                  ├─ Source credibility (NewsAPI > Reddit > X)
                  └─ Confidence band (low if < 5 articles)
                        │                    │
                        ▼                    ▼
                  PostgreSQL           Dashboard widget
                  sentiment table      Gauge + sparkline
                  (history per ticker)
```

**Score interpretation:**
- `+0.6 to +1.0` — Strong positive → BULLISH signal
- `+0.2 to +0.6` — Mild positive → neutral-bullish
- `-0.2 to +0.2` — Neutral → no directional signal
- `-0.6 to -0.2` — Mild negative → neutral-bearish
- `-1.0 to -0.6` — Strong negative → BEARISH signal

---

## 8. Data Flow 6 — Auth & WebSocket Lifecycle

Google OAuth with httpOnly session cookie. No passwords stored. Auth built in one day, never revisited.

```
User clicks "Sign in with Google"
        │
        ▼
React → redirect to accounts.google.com
        │ (user authenticates with Google)
        ▼
Google → sends auth code to /auth/google/callback
        │
        ▼
FastAPI auth service
  ├─ Exchange code for Google user profile
  │    (name, email, avatar URL, google_id)
  ├─ Upsert into PostgreSQL users table
  │    first login  → INSERT new row
  │    returning    → UPDATE last_login
  └─ Set signed httpOnly session cookie
       (session_id stored in Redis, 30-day TTL)
        │
        ▼
Every subsequent request
  Middleware reads cookie → session_id
  Redis lookup session_id → user_id
  User context attached to request
        │
        ▼
WebSocket upgrade
  session_id in query param → validated vs Redis
  WS connection established → user joins their room
        │
        ▼
Live stream to React client
  ├─ Price ticks (every 60s during market hours)
  ├─ Agent status events (thinking... / done)
  ├─ Alert events (from proactive monitor agent)
  └─ Portfolio P&L updates (on price change)
```

**Session rules:** httpOnly, Secure, SameSite=Lax cookie. Session invalidated on logout by deleting Redis key. No JWT, no refresh tokens, no complexity.

---

## 9. Proactive Monitor Agent

The most critical architectural addition. The system watches every portfolio continuously, without the user asking.

```
Celery Beat trigger: every 15 min, 09:15–15:30 IST weekdays
        │
        ▼
Fetch all active portfolios
  SELECT user_id, holdings FROM portfolios WHERE active = true
        │
        ▼
For each user → for each holding (parallelised with Celery workers)
        │
        ▼
Per-stock health check
  ├─ Current price (Redis cache)
  ├─ P&L vs buy price (unrealised %)
  ├─ Sentiment score (last 2 hours)
  ├─ RSI 14-period (computed from TimescaleDB)
  ├─ Volume vs 20-day average
  └─ Compare vs user's stop-loss % and target %
        │
        ▼
Alert threshold evaluation
  ┌──────────────────────────────────────────────────────┐
  │ TRIGGER              │ CONDITION                     │
  ├──────────────────────┼───────────────────────────────┤
  │ Stop-loss breach     │ price ≤ buy_price × (1 - sl%) │
  │ Target hit           │ price ≥ buy_price × (1 + tg%) │
  │ Sentiment crash      │ score drops > 0.4 in 2 hours  │
  │ RSI overbought       │ RSI > 75                       │
  │ RSI oversold         │ RSI < 30                       │
  │ Volume spike         │ volume > 3× 20-day average     │
  │ Concentration risk   │ single stock > 30% portfolio   │
  └──────────────────────┴───────────────────────────────┘
        │ threshold breached?
        ▼ YES
LLM generates actionable insight (natural language)
  "SELL TATASTEEL — down 8.2% from your buy price.
   RSI at 28 (oversold). Negative sentiment from
   12 articles in last 2 hours. Consider cutting
   position or tightening stop-loss."
        │
        ▼
Push to user
  ├─ WebSocket → in-app alert card (real-time)
  ├─ Daily digest email (batched, 15:30 IST)
  └─ Alert logged to PostgreSQL with timestamp
        │
        ▼
User thumbs-up / thumbs-down the alert
  → Feedback stored in alert_feedback table
  → Used to auto-tune alert thresholds over time
```

**End-of-day digest (15:30 IST):** Every user receives a portfolio summary — day's P&L per holding, total portfolio change, sentiment overview, signals generated, and agent's top recommendation for next session.

---

## 10. Agent Memory System

Three distinct memory tiers, all scoped per user. Together they give the agent genuine continuity across sessions.

```
┌─────────────────────────────────────────────────────────────────┐
│  TIER 1 — Working memory  (in-session, ephemeral)               │
│                                                                  │
│  Storage:  Redis                                                 │
│  Key:      session:{session_id}:state                            │
│  TTL:      2 hours of inactivity                                 │
│  Contents: LangGraph state object (serialised JSON)             │
│    • Full conversation turns this session                        │
│    • All tool results accumulated so far                         │
│    • Stocks discussed, decisions made                            │
│    • Current task plan from orchestrator                         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  TIER 2 — Episodic memory  (cross-session, persistent)          │
│                                                                  │
│  Storage:  PostgreSQL — table: user_memory_log                   │
│  Written:  at end of every session (LLM summarises it)          │
│  Loaded:   at start of every new session (injected into prompt) │
│  Contents (LLM-summarised, not raw):                             │
│    • Inferred risk appetite (learned from behaviour)             │
│    • Preferred sectors and stocks                                │
│    • Past decisions and their outcomes                           │
│    • Alert response patterns                                     │
│    • Investment style (momentum / value / dividend)              │
│                                                                  │
│  Example stored summary:                                         │
│    "Prefers large-cap IT (TCS, Infosys). High short-term risk    │
│     tolerance. Ignored 3 SELL signals on INFY in August —        │
│     holds through dips. Dislikes PSU stocks."                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  TIER 3 — Semantic memory  (knowledge retrieval via RAG)         │
│                                                                  │
│  Storage:  ChromaDB (local → upgradeable to Pinecone)            │
│  Embedding: text-embedding-3-small (OpenAI)                      │
│  Retrieval: top-5 cosine similarity per agent query             │
│  Two scopes:                                                     │
│    Global:   NSE filings, sector research, market event notes   │
│    Per-user: every analysis report the agent has generated      │
│              (agent recalls its own past reasoning on a ticker) │
└─────────────────────────────────────────────────────────────────┘

At prompt time — all three tiers assembled:
┌─────────────────────────────────────────────────────────────────┐
│  System prompt                                                   │
│  + Tier 2: user memory profile summary (loaded from PostgreSQL) │
│  + Tier 3: top-5 RAG chunks relevant to this query (ChromaDB)  │
│  + Tier 1: conversation history this session (loaded from Redis)│
│  + Current task + accumulated tool results                       │
└──────────────────────────────────────────────────────────────── ┘
                         ↓
                LLM context window → reasoning
```

---

## 11. Observability & Evaluation

Three pillars. Each answers a different question about system health.

### Pillar 1 — Tracing (LangSmith)

*"What did the agent actually do?"*

Every LLM call, tool invocation, and ReAct step is automatically traced. LangSmith records: full prompt, full response, token count, latency, tool name, arguments, and result. You can replay any agent run step by step.

Key traces to watch:
- Average ReAct iterations per query (target: < 6)
- Tool error rate per tool type
- Queries hitting the 10-iteration cap (indicates agent confusion)

### Pillar 2 — System Metrics (Prometheus + Grafana)

*"Is the system healthy right now?"*

| Metric | Target | Alert threshold |
|--------|--------|----------------|
| Agent P95 response latency | < 8 seconds | > 15 seconds |
| LLM cost per query | < ₹0.50 | > ₹2.00 |
| Data freshness lag | < 90 seconds | > 5 minutes |
| Celery queue depth | < 20 jobs | > 100 jobs |
| Monitor agent success rate | > 99% | < 95% |
| Alert WebSocket delivery rate | > 99.5% | < 98% |
| Redis cache hit rate | > 80% | < 60% |

### Pillar 3 — Signal Evaluation (Backtesting Engine)

*"Is the agent's advice actually correct?"*

Every BUY/SELL/HOLD signal is logged with timestamp and price. A Celery task runs 7 days later and checks outcomes:

```
Signal logged:
  SELL RELIANCE at ₹2,450 on 2024-01-15 10:30 IST
  (sentiment: -0.7, RSI: 78, unrealised gain: +12%)

7 days later:
  RELIANCE price: ₹2,180 → agent was CORRECT

Metrics updated:
  sell_signal_accuracy: +1 correct
  avoided_loss_per_share: ₹270
```

Tracked evaluation metrics:
- Signal accuracy % by type (SELL correct, BUY correct, HOLD correct)
- False alert rate (alerts acted on that led to loss)
- Rolling Sharpe ratio of agent advice
- Alert engagement rate (% of alerts users acted on)
- Alert quality by trigger type (which trigger types are most useful?)

**User feedback loop:** Every alert card has thumbs-up / thumbs-down. After 100 feedback data points per alert type, the system automatically tunes thresholds (e.g. if RSI alerts score 70% thumbs-down, raise threshold from RSI 75 → RSI 80).

---

## 12. Indian Market Data Sources

| Source | Data provided | Frequency | Cost | Library |
|--------|--------------|-----------|------|---------|
| yfinance | OHLCV for NSE/BSE (`RELIANCE.NS`) | 1-min delay intraday | Free | `yfinance` |
| nsetools | Live NSE quotes, gainers/losers | Real-time | Free | `nsetools` |
| nsepy | NSE historical, F&O, indices | Historical | Free | `nsepy` |
| Angel One SmartAPI | Real-time tick data | Real-time | Free tier | `smartapi-python` |
| NewsAPI | Financial headlines (India filtered) | Every 15 min | Free (100 req/day) | `requests` |
| Reddit PRAW | r/IndiaInvestments, r/DalalStreet | Every 30 min | Free | `praw` |
| Moneycontrol RSS | Indian financial news | Every 15 min | Free | `feedparser` |
| Economic Times RSS | Market news | Every 15 min | Free | `feedparser` |

**NSE index tickers:**
- NIFTY 50: `^NSEI`
- NIFTY Bank: `^NSEBANK`
- SENSEX: `^BSESN`
- NIFTY IT: `^CNXIT`

**Upgrade path:** Angel One SmartAPI provides broker-grade real-time data at no cost (requires Angel One account). Zero-cost path to production-quality data when free tiers run out.

---

## 13. Technology Stack

### Backend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API framework | FastAPI | REST endpoints, WebSocket, middleware |
| Agent framework | LangGraph (LangChain) | Orchestration, ReAct loop, state |
| Task queue | Celery + Redis broker | Scheduled jobs, background workers |
| LLM | GPT-4o / Claude Sonnet | Reasoning, synthesis, memory summarisation |
| Embedding model | text-embedding-3-small | RAG vector creation |
| ML — forecasting | Facebook Prophet | Price trend forecasting |
| ML — classification | XGBoost | Buy/sell signal classification |
| ML — deep learning | PyTorch LSTM | Sequential price pattern learning |
| NLP — sentiment | FinBERT | Finance-domain sentiment scoring |
| NLP — fallback | VADER | Lightweight sentiment fallback |
| Vector store | ChromaDB | RAG semantic memory (local) |
| Auth | Authlib + Google OAuth | Google Sign-In, no passwords |

### Data Layer

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Time-series DB | PostgreSQL + TimescaleDB | OHLCV price history |
| Relational DB | PostgreSQL | Users, portfolio, trades, alerts, memory |
| Cache + pub/sub | Redis | Live prices, sessions, WebSocket events |
| Vector DB | ChromaDB | Embeddings for RAG |

### Frontend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | React | SPA dashboard |
| Styling | TailwindCSS | Utility-first styling |
| Charts | Recharts + Lightweight Charts | Price charts, portfolio graphs |
| State | Zustand | Client state management |
| Real-time | Native WebSocket | Price ticks, alerts |

### Infrastructure

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Containerisation | Docker + Docker Compose | All services, one command |
| Tracing | LangSmith | Agent step-by-step observability |
| Metrics | Prometheus + Grafana | System health dashboards |
| CI/CD | GitHub Actions | Auto test + deploy on push |
| Logging | structlog → Grafana Loki | Structured searchable logs |

---

## 14. Alert Trigger Matrix

Every alert the proactive monitor can generate, with trigger condition, priority, and recommended action.

| Alert type | Trigger condition | Priority | Action |
|-----------|-----------------|---------|--------|
| Stop-loss breach | price ≤ buy_price × (1 − sl%) | CRITICAL | SELL — cut losses |
| Target hit | price ≥ buy_price × (1 + tg%) | HIGH | BOOK PROFIT |
| Sentiment crash | score drops > 0.4 in 2 hours | HIGH | CAUTION — review position |
| Sentiment surge | score rises > 0.4 in 2 hours | MEDIUM | ADD opportunity |
| RSI overbought | RSI > 75 | MEDIUM | Consider partial SELL |
| RSI oversold | RSI < 30 | MEDIUM | Consider adding |
| Volume spike | volume > 3× 20-day average | MEDIUM | Investigate unusual activity |
| Concentration risk | single stock > 30% portfolio | LOW | REBALANCE suggested |
| Sector overweight | sector > 40% portfolio | LOW | Diversify |
| Earnings alert | NSE results date within 3 days | INFO | Prepare — high volatility likely |
| 52-week high | price reaches 52W high | INFO | Momentum signal |
| 52-week low | price reaches 52W low | INFO | Distress signal — review thesis |
| Portfolio quiet | no alerts for 7 days | INFO | Weekly health digest |

---

## 15. Summary — All Design Decisions

| Domain | Decision | Rationale |
|--------|---------|-----------|
| Market | Indian (NSE/BSE) | Sufficient free data via yfinance + nsetools |
| Trading mode | Paper trading | Real architecture, zero regulatory complexity |
| Auth | Google OAuth + httpOnly cookie | Zero complexity, production-grade security |
| Agent framework | LangGraph | Native ReAct, parallel nodes, state management |
| Agent mode | Reactive + Proactive (dual track) | User queries + continuous portfolio monitoring |
| Working memory | Redis (LangGraph state, 2hr TTL) | Fast ephemeral session state |
| Episodic memory | PostgreSQL `user_memory_log` | Persistent, LLM-summarised user profiles |
| Semantic memory | ChromaDB RAG | Agent recalls its own past analysis per ticker |
| Tracing | LangSmith | Native LangGraph integration, free tier |
| Metrics | Prometheus + Grafana | Docker-native, free, industry standard |
| Evaluation | Backtesting engine + user feedback | Only honest measure of signal quality |
| Time-series | TimescaleDB | PostgreSQL extension, no new infra needed |
| Live data push | Redis pub/sub → WebSocket | Low-latency, works natively with Celery |
| Sentiment model | FinBERT | Finance-domain tuned, far better than VADER |
| ML models | XGBoost + LSTM + Prophet | Three approaches, ensemble if needed later |
| Data primary | yfinance + nsetools | Free, reliable, covers all NSE/BSE tickers |
| Data upgrade path | Angel One SmartAPI | Free broker-grade real-time data |
| Deployment | Docker Compose | Single command local dev, easy CI/CD target |

---

*Document version: 1.0 — System design finalised.*
*Next phase: database schema design (all tables, columns, indexes, relations).*
