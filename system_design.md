## Document version: 1.0 — System design.

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

---

## 1. Product Vision

FinSight AI solves a single, well-defined problem: **retail investors in India make emotional, uninformed decisions because they lack the tools to continuously research, track, and evaluate their stock holdings.**

The system provides:

- **Reactive intelligence** — the user asks "should I buy more Infosys?" and receives a structured, data-backed recommendation with full rationale.
- **Proactive intelligence** — the system continuously monitors every stock in the user's portfolio and pushes actionable alerts (sell, hold, add) without being asked.
- **Portfolio management** — users can add/remove holdings (ticker, quantity, buy price, buy date) and set personal stop-loss and target percentages per stock.
- **Paper trading** — all trades are executed with virtual money against real NSE/BSE market prices. No real money, no broker integration, no regulatory complexity.

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
│   LLM Engine (GPT-4 / Claude) · ML Models · Vector Store (Chroma)  │
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

Every user query fans out to all four sub-agents in parallel. Their results merge and the LLM synthesises a single structured response.

```
User query: "Should I sell my TATASTEEL position?"
        │
        ▼
FastAPI gateway
  JWT/session verify → parse intent → enqueue job
        │
        ▼
LangGraph Orchestrator
  Decompose → plan → assign to sub-agents
  ┌──────────┬────────────┬──────────┬──────────────┐
  ▼          ▼            ▼          ▼
Research   Sentiment    Risk       Portfolio
Agent      Agent        Agent      Agent
Fundamental News+social  VaR,beta   P&L, weight
screening  score        volatility  fit
  └──────────┴────────────┴──────────┴──────────────┘
                    │ (parallel, merged)
                    ▼
           LLM Synthesis
           Merge · reason · generate recommendation
                    │
                    ▼
           Structured response card
           ┌─────────────────────────────┐
           │ Signal: HOLD                │
           │ Confidence: 72%             │
           │ RSI: 58 (neutral)           │
           │ Sentiment: -0.2 (slightly   │
           │           negative)         │
           │ Rationale: [3 bullet points]│
           │ Risk level: MEDIUM          │
           └─────────────────────────────┘
```

**Key design decisions:**
- Sub-agents run in parallel (LangGraph parallel node), not sequentially.
- Each sub-agent is a separate LangGraph node with its own tool set.
- The orchestrator can re-route or retry individual sub-agents if they fail.
- Response is always structured (not free-text) so the UI can render it as a card.

---

## 4. Data Flow 2 — Market Data Ingestion

Raw data is polled on a schedule, normalised, and split into three destinations simultaneously.

```
External APIs                 Celery Beat Scheduler
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
│ Fundamentals               Detect anomalies · drop duplicates
├────────────┤                               │
│ NewsAPI /  │──────────────►  ┌─────────────┼──────────────┐
│ Reddit     │                 ▼             ▼              ▼
└────────────┘           TimescaleDB   PostgreSQL       Redis
                         OHLCV history  Fundamentals    Latest price
                         (permanent)    Metadata        60s TTL
                                                        │
                                                        ▼
                                                   WebSocket pub/sub
                                                   Push live ticks
                                                   to React dashboard
```

**NSE market hours awareness:**
- Celery Beat uses IST timezone (Asia/Kolkata).
- High-frequency polling only between 09:15–15:30 IST, Mon–Fri.
- Outside hours: hourly polling for news/sentiment, daily EOD snapshot.
- Public holidays handled via NSE holiday calendar (fetched quarterly, stored in PostgreSQL).

**Indian tickers format:**
- NSE stocks: `RELIANCE.NS`, `TCS.NS`, `INFY.NS`
- BSE stocks: `500325.BO`, `532540.BO`
- Indices: `^NSEI` (NIFTY 50), `^BSESN` (SENSEX)

---

## 5. Data Flow 3 — Agent ReAct Loop

The agent cycles through Think → Act → Observe until it has enough context to answer. This is the internal loop of every sub-agent.

```
Task from orchestrator
        │
        ▼
    ┌──────────────────────────────────────────────┐
    │                  THINK                        │
    │  LLM reasons: "What tool do I need next?"    │
    │  Looks at conversation history + tool results │
    └──────────────────────┬───────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────┐
    │                   ACT                         │
    │  Select and call one tool:                   │
    │  ├─ fetch_price_data(ticker, period)         │
    │  │    → queries TimescaleDB                  │
    │  ├─ get_sentiment_score(ticker)              │
    │  │    → queries PostgreSQL sentiment table   │
    │  ├─ run_ml_model(ticker, model_type)         │
    │  │    → XGBoost / LSTM / Prophet inference  │
    │  ├─ rag_search(query)                        │
    │  │    → ChromaDB similarity search           │
    │  ├─ get_fundamentals(ticker)                 │
    │  │    → PostgreSQL fundamentals table        │
    │  └─ get_portfolio_position(user_id, ticker)  │
    │       → PostgreSQL portfolio table           │
    └──────────────────────┬───────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────┐
    │                 OBSERVE                       │
    │  Append tool result to context window        │
    │  LangGraph state updated                     │
    └──────────────────────┬───────────────────────┘
                           │
               ┌───────────┴────────────┐
               │                        │
          Need more?               Have enough?
               │                        │
               └──► THINK again         └──► Return final answer
                    (loop up to               to orchestrator
                     10 iterations)
```

**Tool call limits:** Max 10 iterations per sub-agent run (configurable). If exceeded, agent returns best available answer with a low-confidence flag.

**LangSmith traces every step** — every Think/Act/Observe cycle is recorded with full prompt, token count, and latency.

---

## 6. Data Flow 4 — Paper Trade Execution

Every trade goes through validation → risk check → real price fetch → simulated fill → dual write.

```
User places paper trade
"BUY 10 shares of INFY"
        │
        ▼
Trade engine validation
  ├─ Sufficient virtual balance?        → FAIL: reject with reason
  ├─ Position size ≤ 20% of portfolio?  → FAIL: reject with reason
  ├─ Valid NSE/BSE ticker?              → FAIL: reject with reason
  └─ Market hours or allow off-hours?   → configurable
        │
        ▼ (pass)
Risk limit check
  ├─ Portfolio VaR gate (max 15% daily VaR)
  ├─ Single-stock concentration (max 30%)
  └─ Sector concentration (max 40%)
        │
        ▼ (pass)
Fetch fill price
  Redis cache → latest real NSE price (60s TTL)
  Fallback: yfinance real-time quote if cache stale
        │
        ▼
Simulate fill
  Apply 0.05% slippage (market impact model)
  Deduct (price × quantity × 1.0005) from virtual balance
  Add STT + exchange charges (0.1% on sell side, NSE rates)
        │
        ├─────────────────────┐
        ▼                     ▼
PostgreSQL trade log    Portfolio state update
  trade_id              holdings table
  user_id               avg_cost recalculated
  ticker                unrealised_pnl updated
  quantity              portfolio_weight updated
  fill_price            total_invested updated
  slippage
  timestamp
  virtual_balance_after
        │
        ▼
Trade confirmation pushed via WebSocket
Signal logged to eval store (for backtesting)
```

---

## 7. Data Flow 5 — Sentiment Pipeline

Four sources → single cleaner → FinBERT scoring → volume-weighted aggregation → per-ticker sentiment score.

```
NewsAPI          Reddit              X (Twitter)      RSS Feeds
headlines        r/IndiaInvestments  Cashtags         Moneycontrol
every 15 min     r/IndianStockMarket mentions         Economic Times
                 r/DalalStreet
     │                │                  │                │
     └────────────────┴──────────────────┴────────────────┘
                                │
                                ▼
                   Collector + text cleaner
                   ├─ Deduplicate (URL + content hash)
                   ├─ Strip HTML / extract plain text
                   ├─ Extract ticker mentions (RELIANCE, TATASTEEL...)
                   ├─ Filter: must mention at least one tracked ticker
                   └─ Language detect: keep English + Hindi (transliterate)
                                │
                                ▼
                   NLP sentiment scoring
                   ├─ Primary:  FinBERT (finance-tuned BERT)
                   │            Outputs: positive / negative / neutral
                   │            Score: -1.0 to +1.0
                   └─ Fallback: VADER (if FinBERT unavailable)
                                │
                                ▼
                   Score aggregation per ticker
                   ├─ Volume-weighted (more articles = more weight)
                   ├─ Recency decay (exponential, half-life: 4 hours)
                   ├─ Source credibility weight (NewsAPI > Reddit > X)
                   └─ Confidence band (low if <5 articles)
                         │                    │
                         ▼                    ▼
                   PostgreSQL           Dashboard widget
                   sentiment table      Gauge + sparkline
                   (history per         colour: red/amber/green
                    ticker + timestamp)
```

**Sentiment score interpretation:**
- `+0.6 to +1.0` → Strong positive → BULLISH signal contribution
- `+0.2 to +0.6` → Mild positive → neutral-bullish
- `-0.2 to +0.2` → Neutral → no directional signal
- `-0.6 to -0.2` → Mild negative → neutral-bearish
- `-1.0 to -0.6` → Strong negative → BEARISH signal contribution

---

## 8. Data Flow 6 — Auth & WebSocket Lifecycle

Google OAuth with httpOnly session cookie. No passwords stored. Auth handled in one day, never revisited.

```
User clicks "Sign in with Google"
        │
        ▼
React → redirect to accounts.google.com
        │
        ▼ (user logs in with Google)
Google → sends auth code to /auth/google/callback
        │
        ▼
FastAPI auth service
  ├─ Exchange code for Google user profile
  │    (name, email, avatar URL, google_id)
  ├─ Upsert into PostgreSQL users table
  │    first login  → INSERT new row
  │    returning    → UPDATE last_login timestamp
  └─ Set signed httpOnly session cookie
       (session_id → Redis, 30-day TTL)
        │
        │ FAIL path ──► 401 + "Google auth failed"
        │
        ▼ (success)
User is authenticated. Cookie sent to browser.
        │
        ▼
Every subsequent request
  FastAPI middleware reads cookie → session_id
  Looks up session_id in Redis → user_id
  Attaches user context to request
        │
        ▼
WebSocket upgrade (for live data)
  Token in query param → validated against Redis session
  WS connection established → user joins their room
        │
        ▼
Live stream to React client (over WebSocket)
  ├─ Price ticks (every 60s during market hours)
  ├─ Agent status (thinking... / done)
  ├─ Alert events (from monitor agent)
  └─ Portfolio P&L updates (on price change)
```

**Session management:**
- Session cookie: httpOnly, Secure, SameSite=Lax, 30-day expiry.
- Session store: Redis hash `session:{session_id}` → `{user_id, email, created_at}`.
- No JWT — no refresh token complexity. Session is invalidated on logout by deleting Redis key.

---

## 9. Proactive Monitor Agent

The most important architectural addition. The system continuously watches every portfolio without the user needing to ask.

```
Celery Beat trigger (every 15 min, 09:15–15:30 IST)
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
  ├─ P&L vs buy price
  ├─ Sentiment score (last 2 hours)
  ├─ RSI (14-period, from TimescaleDB)
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
  │ Sentiment crash      │ score drops >0.4 in 2 hours   │
  │ RSI overbought       │ RSI > 75                       │
  │ RSI oversold         │ RSI < 30                       │
  │ Volume spike         │ volume > 3× 20-day avg         │
  │ Concentration risk   │ single stock > 30% portfolio   │
  └──────────────────────┴───────────────────────────────┘
        │ threshold breached?
        ▼ YES
LLM generates actionable insight
  e.g. "SELL TATASTEEL — down 8.2% from your buy price.
        RSI at 28 (oversold). Negative news sentiment
        from 12 articles in last 2 hours. Consider
        cutting position or setting a tighter stop."
        │
        ▼
Push to user (all channels simultaneously)
  ├─ WebSocket → in-app alert card (real-time)
  ├─ Daily digest email (batched, sent at 15:30 IST)
  └─ Alert logged to PostgreSQL (with timestamp, type, signal)
        │
        ▼
User can thumbs-up / thumbs-down the alert
  → Feedback stored in eval store
  → Used to tune alert thresholds over time
```

**End-of-day digest (15:30 IST):**
Every user receives a portfolio summary email with: day's P&L per holding, total portfolio change, sentiment overview, notable signals generated during the day, and the agent's top recommendation for tomorrow.

---

## 10. Agent Memory System

Three distinct memory tiers, all scoped per user. Together they give the agent genuine continuity.

```
┌─────────────────────────────────────────────────────────────────┐
│  TIER 1 — Working memory  (in-session, ephemeral)               │
│                                                                  │
│  Storage: Redis                                                  │
│  Key: session:{session_id}:state                                 │
│  TTL: 2 hours of inactivity                                      │
│  Contents: LangGraph state object (serialised)                   │
│    • Full conversation turns this session                        │
│    • Tool results accumulated so far                             │
│    • Stocks discussed, decisions made                            │
│    • Current task plan from orchestrator                         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  TIER 2 — Episodic memory  (cross-session, persistent)          │
│                                                                  │
│  Storage: PostgreSQL table: user_memory_log                      │
│  Written: at end of every session (LLM summarises the session)  │
│  Loaded: at start of every new session (injected into prompt)   │
│  Contents (LLM-summarised, not raw logs):                        │
│    • Inferred risk appetite (learned from behaviour)             │
│    • Preferred sectors / stocks                                  │
│    • Past decisions and their outcomes                           │
│    • Alert response patterns ("user ignored 3 SELL alerts")      │
│    • Investment style (momentum / value / dividend)              │
│                                                                  │
│  Example stored summary:                                         │
│  "User prefers large-cap IT (TCS, Infosys). High short-term      │
│   risk tolerance. Has ignored 3 SELL signals on INFY in August   │
│   — appears to hold through dips. Responds well to sentiment     │
│   analysis data. Dislikes PSU stocks."                           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  TIER 3 — Semantic memory  (knowledge retrieval via RAG)         │
│                                                                  │
│  Storage: ChromaDB (local, upgradeable to Pinecone)              │
│  Embedding model: text-embedding-3-small (OpenAI)               │
│  Retrieval: top-5 similarity search per agent query             │
│  Two scopes:                                                     │
│    • Global: NSE company filings, sector research notes,        │
│              historical market events, agent analysis reports    │
│    • Per-user: user's own past analysis reports embedded         │
│                so agent recalls what it said about a stock before│
│                                                                  │
│  Contents:                                                       │
│    • Every analysis report the agent generates (auto-embedded)  │
│    • NSE quarterly results summaries                            │
│    • Sector rotation notes                                       │
│    • Historical alert rationales (what triggered past alerts)   │
└─────────────────────────────────────────────────────────────────┘

At prompt time — all three tiers assembled:
┌──────────────────────────────────────────────────────┐
│  System prompt                                        │
│  + Tier 2: user memory profile summary               │
│  + Tier 3: top-5 RAG chunks relevant to this query  │
│  + Tier 1: conversation history this session         │
│  + Current task + tool results                        │
└──────────────────────────────────────────────────────┘
                    ↓
               LLM context window
```

---

## 11. Observability & Evaluation

Three pillars. Each answers a different question about system health.

### Pillar 1 — Tracing (LangSmith)

*"What did the agent actually do?"*

Every LLM call, tool invocation, and ReAct step is automatically traced. LangSmith records: full prompt sent, full response received, token count, latency, tool name and arguments, tool result.

You can replay any agent run step-by-step and see exactly why it gave a particular recommendation.

**Key traces to monitor:**
- Average ReAct iterations per query (target: <6)
- Tool error rate per tool type
- Queries that hit the 10-iteration limit (indicates confusion)

### Pillar 2 — Metrics (Prometheus + Grafana)

*"Is the system healthy right now?"*

| Metric | Target | Alert if |
|--------|--------|----------|
| Agent P95 response latency | < 8 seconds | > 15s |
| LLM cost per query (₹) | < ₹0.50 | > ₹2.00 |
| Data freshness lag | < 90 seconds | > 5 min |
| Celery queue depth | < 20 jobs | > 100 jobs |
| Monitor agent run success rate | > 99% | < 95% |
| Alert delivery rate (WebSocket) | > 99.5% | < 98% |
| Redis cache hit rate | > 80% | < 60% |

### Pillar 3 — Evaluation (Backtesting Engine)

*"Is the agent's advice actually good?"*

Every BUY/SELL/HOLD signal the agent generates is logged with timestamp and price. A Celery task runs 7 days later and checks what actually happened:

```
Signal logged:
  SELL RELIANCE at ₹2,450 on 2024-01-15 10:30 IST
  (sentiment: -0.7, RSI: 78, P&L from buy: +12%)

7 days later:
  RELIANCE price: ₹2,180
  Agent was RIGHT → signal_outcome = CORRECT

Metrics updated:
  sell_signal_accuracy += 1 correct / total
  avoided_loss = ₹270/share
```

**Tracked evaluation metrics:**
- Signal accuracy % (SELL correct, BUY correct, HOLD correct, by category)
- False alert rate (alerts user acted on that led to loss)
- Rolling Sharpe ratio of agent advice (if all signals were followed)
- User engagement rate (what % of alerts did users act on)
- Alert quality by type (stop-loss alerts more useful than RSI alerts?)

**User feedback loop:**
Every alert card in the UI has thumbs-up / thumbs-down. Feedback is stored in `alert_feedback` table. After 100 feedback data points per alert type, the system automatically adjusts thresholds (e.g. if RSI alerts get 70% thumbs-down, raise the RSI threshold from 75 to 80).

---

## 12. Indian Market Data Sources

| Source | Data provided | Frequency | Cost | Python library |
|--------|--------------|-----------|------|----------------|
| yfinance | OHLCV for NSE/BSE (`RELIANCE.NS`) | 1-min delay intraday, EOD | Free | `yfinance` |
| nsetools | Live NSE quotes, gainers/losers | Real-time | Free | `nsetools` |
| nsepy | NSE historical, F&O, indices | Historical | Free | `nsepy` |
| Angel One SmartAPI | Real-time tick data, historical | Real-time | Free tier | `smartapi-python` |
| NewsAPI | Financial headlines (filtered India) | Every 15 min | Free (100 req/day) | `requests` |
| Reddit API | r/IndiaInvestments, r/DalalStreet | Every 30 min | Free | `praw` |
| Moneycontrol RSS | Indian financial news | Every 15 min | Free | `feedparser` |
| Economic Times RSS | Market news | Every 15 min | Free | `feedparser` |

**NSE index tickers for yfinance:**
- NIFTY 50: `^NSEI`
- NIFTY Bank: `^NSEBANK`
- SENSEX: `^BSESN`
- NIFTY IT: `^CNXIT`

**Upgrade path:** When free tiers run out, Angel One SmartAPI provides broker-grade real-time data at no cost (requires Angel One account). Zero-cost path to production-quality data.

---

## 13. Technology Stack

### Backend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API framework | FastAPI (Python) | REST endpoints, WebSocket, middleware |
| Agent framework | LangGraph (LangChain) | Orchestration, ReAct loop, state management |
| Task queue | Celery + Redis broker | Scheduled jobs, background workers |
| LLM | GPT-4o / Claude Sonnet | Reasoning, synthesis, memory summarisation |
| Embedding | text-embedding-3-small | RAG vector creation |
| ML — forecasting | Facebook Prophet | Price trend forecasting |
| ML — classification | XGBoost | Buy/sell signal classification |
| ML — deep learning | PyTorch LSTM | Sequential price pattern learning |
| NLP — sentiment | FinBERT | Finance-domain sentiment scoring |
| NLP — fallback | VADER | Lightweight sentiment fallback |
| Vector store | ChromaDB | RAG semantic memory (local) |
| Auth | Authlib + Google OAuth | Google Sign-In, zero password storage |

### Data Layer

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Time-series DB | PostgreSQL + TimescaleDB | OHLCV price history |
| Relational DB | PostgreSQL | Users, portfolio, trades, alerts, memory |
| Cache / pub-sub | Redis | Live prices, sessions, WebSocket events |
| Vector DB | ChromaDB | Embeddings for RAG |

### Frontend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | React | SPA dashboard |
| Styling | TailwindCSS | Utility-first styling |
| Charts | Recharts + Lightweight Charts (TradingView) | Price charts, portfolio graphs |
| State | Zustand | Client state management |
| WebSocket | native browser WebSocket | Live price ticks, alerts |

### Infrastructure

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Containerisation | Docker + Docker Compose | Local dev, all services in one command |
| Tracing | LangSmith | Agent step-by-step observability |
| Metrics | Prometheus + Grafana | System health dashboards |
| CI/CD | GitHub Actions | Auto test + deploy on push |
| Logging | Python structlog → Grafana Loki | Structured logs, searchable |

---

## 14. Alert Trigger Matrix

Every alert the proactive monitor can generate, with its trigger condition, priority, and recommended action.

| Alert type | Trigger condition | Priority | Recommended action |
|-----------|-----------------|---------|-------------------|
| Stop-loss breach | price ≤ buy_price × (1 − sl%) | 🔴 CRITICAL | SELL — cut losses |
| Target hit | price ≥ buy_price × (1 + tg%) | 🟢 HIGH | BOOK PROFIT — sell partial or full |
| Sentiment crash | score drops >0.4 in 2 hours | 🟠 HIGH | CAUTION — review position |
| Sentiment surge | score rises >0.4 in 2 hours | 🟢 MEDIUM | ADD opportunity |
| RSI overbought | RSI > 75 | 🟠 MEDIUM | Consider partial SELL |
| RSI oversold | RSI < 30 | 🟢 MEDIUM | Consider adding |
| Volume spike | volume > 3× 20-day average | 🟡 MEDIUM | Investigate — unusual activity |
| Concentration risk | single stock > 30% of portfolio | 🟠 LOW | REBALANCE suggested |
| Sector overweight | sector > 40% of portfolio | 🟡 LOW | Diversify suggestion |
| Q results alert | NSE earnings date within 3 days | 🔵 INFO | Prepare — high volatility expected |
| 52-week high | price reaches 52W high | 🟢 INFO | Momentum signal |
| 52-week low | price reaches 52W low | 🔴 INFO | Distress signal — review thesis |
| Portfolio flat | no alerts for 7 days | 🔵 INFO | Weekly digest with health score |

---

## Summary — All Design Decisions

| Domain | Decision | Rationale |
|--------|---------|-----------|
| Market | Indian (NSE/BSE) | Sufficient free data via yfinance + nsetools |
| Trading mode | Paper trading | Real architecture, zero regulatory complexity |
| Auth | Google OAuth + httpOnly cookie | Zero complexity, production-grade security |
| Agent framework | LangGraph | Native ReAct, parallel nodes, state management |
| Agent mode | Reactive + Proactive (dual track) | User queries + continuous portfolio monitoring |
| Working memory | Redis (LangGraph state, 2hr TTL) | Fast ephemeral session state |
| Episodic memory | PostgreSQL `user_memory_log` | Persistent, LLM-summarised user profiles |
| Semantic memory | ChromaDB RAG | Agent recalls its own past analysis |
| Tracing | LangSmith | Native LangGraph integration, free tier |
| Metrics | Prometheus + Grafana | Docker-native, free, industry standard |
| Evaluation | Backtesting engine + user feedback | Only honest measure of signal quality |
| Time-series | TimescaleDB | PostgreSQL extension, no new infra needed |
| Live data push | Redis pub/sub → WebSocket | Low-latency, works with Celery |
| Sentiment model | FinBERT | Finance-domain tuned, significantly better than VADER |
| ML models | XGBoost + LSTM + Prophet | Three approaches, ensemble if needed |
| Data primary | yfinance + nsetools | Free, reliable, covers all NSE/BSE tickers |
| Data upgrade | Angel One SmartAPI | Free broker-grade real-time data |
| Deployment | Docker Compose | Single command local dev, easy CI/CD |

---


