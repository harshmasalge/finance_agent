# FinSight AI — Implementation Plan: Complete the Body

> **Goal:** After completing this plan, the only remaining work is plugging in the LangGraph AI brain.
> Every data pipeline, REST endpoint, WebSocket flow, UI component, and Celery task must be real and working.
> The AI chat will still return a placeholder — that is intentional and acceptable.

---

## What already exists (do not touch)

- `docker-compose.yml` — TimescaleDB, Redis, ChromaDB all configured correctly
- `backend/db/models.py` — all 5 models: `User`, `OHLCVData`, `Portfolio`, `TradeLog`, `SentimentScore`
- `backend/db/database.py` — PostgreSQL + Redis connections
- `backend/scripts/init_db.py` — creates tables, converts to TimescaleDB hypertable
- `backend/providers/market_data_provider.py` — yfinance abstraction
- `backend/services/auth.py` — Redis session + httpOnly cookie (fully working)
- `backend/services/trading_engine.py` — full BUY/SELL execution with slippage, STT, concentration check
- `backend/services/sentiment_pipeline.py` — FinBERT + VADER scoring and storage (engine exists, not triggered)
- `backend/tasks/data_ingestion.py` — live price + EOD historical Celery tasks (working but hardcoded tickers)
- `backend/websockets/manager.py` — per-user WebSocket room manager
- `backend/websockets/redis_listener.py` — Redis pub/sub listener subscribed to `live_prices` and `user_alerts`
- `backend/celery_app.py` — Celery with IST timezone and Beat schedule
- `backend/main.py` — FastAPI app with auth routes, mock login, WebSocket endpoint
- `frontend/src/App.tsx` — shell with sidebar nav, auth check, tab routing
- `frontend/src/components/Dashboard.tsx` — live WebSocket price chart for RELIANCE.NS

---

## Phase 1 — Database: add missing tables

**File to edit:** `backend/db/models.py`

Add three new SQLAlchemy models at the bottom of the file:

**1. `AlertLog`**
Fields: `id`, `user_id` (FK → users), `ticker`, `alert_type` (String — e.g. "STOP_LOSS_BREACH"), `message` (Text), `signal` (String — BUY/SELL/HOLD/CAUTION), `price_at_alert` (Float), `is_read` (Boolean, default False), `created_at` (DateTime, server_default now)
Add relationship on `User`: `alerts = relationship("AlertLog", back_populates="owner")`

**2. `AlertFeedback`**
Fields: `id`, `alert_id` (FK → alert_log), `user_id` (FK → users), `is_positive` (Boolean), `created_at` (DateTime)

**3. `SignalLog`**
Fields: `id`, `user_id` (FK → users), `ticker`, `signal` (String — BUY/SELL/HOLD), `price_at_signal` (Float), `rationale` (Text), `outcome` (String, nullable — CORRECT/INCORRECT/PENDING), `outcome_price` (Float, nullable), `outcome_checked_at` (DateTime, nullable), `created_at` (DateTime, server_default now)

**File to edit:** `backend/scripts/init_db.py`
After `Base.metadata.create_all`, add `db.execute` to run `CREATE INDEX` on `alert_log(user_id, is_read)` and `signal_log(created_at)`. Run this script after changes.

---

## Phase 2 — Fix `TRACKED_TICKERS` to be dynamic

**File to edit:** `backend/tasks/data_ingestion.py`

Remove the hardcoded `TRACKED_TICKERS` list at the top.

In both `fetch_live_prices` and `fetch_and_store_historical_data`, at the start of the task body:
- Open a `SessionLocal()` DB session
- Query `SELECT DISTINCT ticker FROM portfolios WHERE quantity > 0`
- Use that result as the ticker list
- Always include `["^NSEI", "^BSESN"]` as baseline indices regardless

If the query returns nothing (no holdings yet), fall back to `["RELIANCE.NS", "TCS.NS", "INFY.NS", "^NSEI"]`.

---

## Phase 3 — Portfolio REST API

**New file:** `backend/routers/portfolio.py`

Create a FastAPI `APIRouter` with prefix `/portfolio` and implement these endpoints:

**GET `/portfolio/holdings`**
- Auth required (read session cookie via `AuthService.get_current_user_id`)
- Query all `Portfolio` rows for `user_id` where `quantity > 0`
- For each holding, fetch current price from Redis (`live_price:{ticker}`) with yfinance fallback
- Calculate `current_value`, `unrealised_pnl`, `unrealised_pnl_pct` per holding
- Return list of holdings with all fields including `sl_pct`, `tg_pct`

**POST `/portfolio/trade`**
- Auth required
- Request body: `{ ticker: str, side: "BUY"|"SELL", quantity: float }`
- Call `TradingEngine(db).execute_trade(user_id, ticker, TradeSide[side], quantity)`
- On `TradeException`, return HTTP 400 with the error message
- On success, return the trade log entry
- After commit, publish to Redis channel `live_prices` with updated balance so WebSocket reflects it

**PATCH `/portfolio/holdings/{ticker}/limits`**
- Auth required
- Request body: `{ sl_pct: float | null, tg_pct: float | null }`
- Update `sl_pct` and `tg_pct` on the matching `Portfolio` row for this user + ticker
- Return updated holding

**DELETE `/portfolio/holdings/{ticker}`**
- Auth required
- Only allow if `quantity == 0` (position already closed)
- Delete the `Portfolio` row
- Return `{ message: "Holding removed" }`

**GET `/portfolio/trades`**
- Auth required
- Return last 50 `TradeLog` entries for the user, ordered by `timestamp DESC`

**File to edit:** `backend/main.py`
Import the new router and add: `app.include_router(portfolio_router)`

---

## Phase 4 — Sentiment ingestion Celery task

**New file:** `backend/tasks/sentiment_ingestion.py`

Create a Celery task `run_sentiment_ingestion` that:

1. Fetches tickers dynamically from DB (same pattern as Phase 2)
2. Fetches news from NewsAPI — endpoint `https://newsapi.org/v2/everything`, query per ticker (strip `.NS`), language `en`, `sortBy=publishedAt`, last 6 hours. Read API key from env var `NEWSAPI_KEY`.
3. Fetches Reddit posts from `r/IndiaInvestments` and `r/DalalStreet` using PRAW. Read `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` from env vars. Fetch top 25 hot posts from each subreddit.
4. Fetches RSS from Moneycontrol (`https://www.moneycontrol.com/rss/latestnews.xml`) and Economic Times Markets (`https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms`) using `feedparser`. Take entries from last 2 hours.
5. Deduplicate all collected texts by hashing content.
6. For each text, call `SentimentPipeline(db).process_and_store(text, source, tracked_tickers)`.
7. Log count of articles processed per source.

**File to edit:** `backend/celery_app.py`
- Add `"backend.tasks.sentiment_ingestion"` to the `include` list
- Add Beat schedule entry: run `run_sentiment_ingestion` every 15 minutes during IST market hours (09:00–16:00, Mon–Fri). Use `crontab(minute="*/15", hour="9-16", day_of_week="1-5")`

---

## Phase 5 — Proactive monitor Celery task

**New file:** `backend/tasks/portfolio_monitor.py`

Create a Celery task `run_portfolio_monitor` that:

1. Opens DB session, fetches all `Portfolio` rows where `quantity > 0`, grouped by `user_id`
2. For each unique user, for each holding, runs these checks:

**Check A — Stop-loss breach**
`current_price <= avg_cost * (1 - sl_pct/100)` → if `sl_pct` is set

**Check B — Target hit**
`current_price >= avg_cost * (1 + tg_pct/100)` → if `tg_pct` is set

**Check C — Sentiment crash**
Query last two `SentimentScore` rows for the ticker. If latest score minus older score < -0.4, trigger.

**Check D — RSI overbought/oversold**
Query last 15 `OHLCVData` rows for the ticker from TimescaleDB. Compute RSI-14. If RSI > 75 or RSI < 30, trigger.

**Check E — Volume spike**
Query last 21 `OHLCVData` rows. If today's volume > 3× average of prior 20 days, trigger.

3. For each triggered check, create an `AlertLog` row (write to DB) with:
   - `alert_type` matching the check name
   - `message` as a plain-English string describing what triggered (no LLM needed — template strings are fine here, e.g. `"RELIANCE.NS down 8.2% from your buy price of ₹2400. Stop-loss at ₹2208 breached."`)
   - `signal` set to SELL/HOLD/BUY based on the check type
   - `price_at_alert` from Redis

4. After writing to DB, publish to Redis channel `user_alerts`:
```
{ "user_id": <int>, "alert_type": <str>, "ticker": <str>, "message": <str>, "signal": <str> }
```
The WebSocket listener in `redis_listener.py` already handles this channel — it will route to the correct user immediately.

5. Log total alerts generated per run.

**File to edit:** `backend/celery_app.py`
- Add `"backend.tasks.portfolio_monitor"` to the `include` list
- Add Beat schedule entry: every 15 minutes, 09:00–16:00 IST, Mon–Fri

---

## Phase 6 — Alerts REST API

**New file:** `backend/routers/alerts.py`

Create a FastAPI `APIRouter` with prefix `/alerts`:

**GET `/alerts`**
- Auth required
- Return last 30 `AlertLog` entries for user ordered by `created_at DESC`
- Include `is_read` field

**PATCH `/alerts/{alert_id}/read`**
- Auth required
- Set `is_read = True` on the alert
- Verify alert belongs to this user

**POST `/alerts/{alert_id}/feedback`**
- Auth required
- Request body: `{ is_positive: bool }`
- Create `AlertFeedback` row
- Return `{ message: "Feedback recorded" }`

**GET `/alerts/unread-count`**
- Auth required
- Return `{ count: int }` of unread alerts for the user

**File to edit:** `backend/main.py`
Import and register the alerts router.

---

## Phase 7 — Add `.env.example` and fix security issues

**New file:** `.env.example` at repo root
```
POSTGRES_URL=postgresql://postgres:password@localhost:5432/finsight
REDIS_URL=redis://localhost:6379/0
NEWSAPI_KEY=your_newsapi_key_here
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=finsight_ai/1.0
SESSION_SECRET=change_this_to_a_random_string_in_production
ENVIRONMENT=development
```

**File to edit:** `backend/services/auth.py`
Change `secure=False` to `secure = os.getenv("ENVIRONMENT", "development") != "development"`

**File to edit:** `backend/main.py`
Replace deprecated `@app.on_event("startup")` with a `lifespan` context manager using `asynccontextmanager` from `contextlib`. Move `asyncio.create_task(redis_listener())` inside the lifespan startup block.

**File to edit:** `backend/websockets/manager.py` → `websocket_endpoint` in `main.py`
The `/ws/{user_id}` endpoint accepts any `user_id` without validation. Add a check: read the session cookie from the WebSocket headers, call `AuthService.get_current_user_id`, and close the connection with code 1008 if the session user does not match the path `user_id`.

---

## Phase 8 — Update Docker Compose

**File to edit:** `docker-compose.yml`

Add these services:

**`backend`**
- Build from `./backend`
- Command: `uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload`
- Env vars from `.env` file
- Depends on: `db`, `redis`, `chromadb`
- Ports: `8001:8001`

**`celery_worker`**
- Same build as backend
- Command: `celery -A backend.celery_app worker --loglevel=info --concurrency=4`
- Depends on: `db`, `redis`

**`celery_beat`**
- Same build as backend
- Command: `celery -A backend.celery_app beat --loglevel=info`
- Depends on: `db`, `redis`

**`frontend`**
- Build from `./frontend`
- Command: `npm run dev -- --host`
- Ports: `5173:5173`
- Depends on: `backend`

Also add a `backend/Dockerfile` and `frontend/Dockerfile` (simple ones — Python 3.11 slim + pip install, Node 20 alpine + npm install respectively).

---

## Phase 9 — Portfolio UI (replace mock data)

**File to replace:** `frontend/src/components/Portfolio.tsx`

Remove all hardcoded `mockHoldings`. Rebuild the component to:

**On mount:** Call `GET /portfolio/holdings` with `credentials: 'include'`. Store in state.

**Holdings table:** Same columns as before (ticker, shares, avg cost, LTP, total return) but now driven by the API response. Add two extra columns: `Stop Loss` and `Target` showing the `sl_pct` and `tg_pct` values if set (or "—" if not).

**Add trade form:** A small form below the table with fields: Ticker (text input), Side (BUY/SELL toggle), Quantity (number input), and a Submit button. On submit, call `POST /portfolio/trade`. Show success/error inline. On success, refresh holdings.

**Set limits form:** Clicking a row expands it to show two inline inputs for stop-loss % and target %. On blur/submit, call `PATCH /portfolio/holdings/{ticker}/limits`. Show saved confirmation.

**Trade history section:** Below the holdings, call `GET /portfolio/trades` and show last 10 trades in a compact table (date, ticker, side, quantity, fill price, balance after).

**State management:** Use `useEffect` + `useState`. No external state library needed for this component.

---

## Phase 10 — Alerts UI

**New file:** `frontend/src/components/Alerts.tsx`

**On mount and every 30 seconds:** Call `GET /alerts` and `GET /alerts/unread-count`.

**Alert card component:** Each alert shows: ticker name, alert type badge (colour-coded — red for STOP_LOSS_BREACH, green for TARGET_HIT, amber for RSI/sentiment), the message string, signal badge (BUY/SELL/HOLD), timestamp, and thumbs-up/thumbs-down buttons.

**On thumbs click:** Call `POST /alerts/{alert_id}/feedback` with `{ is_positive: true/false }`. Disable buttons after vote.

**On card click/view:** Call `PATCH /alerts/{alert_id}/read`.

**File to edit:** `frontend/src/App.tsx`
- Import `Alerts` component
- Add a `Bell` icon nav item for `activeTab === 'alerts'`
- Show unread count badge on the Bell icon (red dot with number)
- Add `{activeTab === 'alerts' && <Alerts />}` to the main content area

---

## Phase 11 — AI Chat: wire to a stub backend endpoint (no LangGraph yet)

**New file:** `backend/routers/agent.py`

Create a FastAPI `APIRouter` with prefix `/agent`:

**POST `/agent/chat`**
- Auth required
- Request body: `{ message: str, conversation_history: list }`
- For now, return a structured stub response:
```json
{
  "response": "AI brain not yet connected. LangGraph integration coming next.",
  "signal": null,
  "confidence": null,
  "sources_used": []
}
```
- Log the incoming message and user_id with structlog so you can see traffic.
- The response schema must already be the final shape the LangGraph agent will return. Do not change this schema later.

**File to edit:** `backend/main.py`
Register the agent router.

**File to edit:** `frontend/src/components/AIChat.tsx`
Replace the `setTimeout` placeholder with a real `fetch('http://localhost:8001/agent/chat', { method: 'POST', ... })` call. Send `message` and the last 10 `messages` as `conversation_history`. On response, render `data.response` as the AI message. Keep the same chat bubble UI.

---

## Completion checklist

After all phases are done, verify:

- [ ] `docker-compose up` starts all services with no errors
- [ ] `python backend/scripts/init_db.py` creates all 8 tables including new ones
- [ ] Live price updates arrive in Dashboard via WebSocket within 60 seconds
- [ ] User can add a BUY trade in Portfolio UI and see their balance decrease
- [ ] User can set stop-loss and target % on a holding
- [ ] Trade history shows in Portfolio UI
- [ ] Sentiment ingestion Celery task runs on schedule and writes rows to `sentiment_scores`
- [ ] Portfolio monitor task runs and writes to `alert_log` when thresholds are breached
- [ ] Alerts appear in the Alerts UI in real time via WebSocket
- [ ] Thumbs up/down feedback records in `alert_feedback`
- [ ] AI Chat sends to the stub endpoint and receives a response
- [ ] `.env.example` exists with all required keys documented
- [ ] No hardcoded mock data anywhere in the frontend

---

## What remains after this plan (the brain)

- LangGraph orchestrator with 4 parallel sub-agents
- Agent tool implementations (6 tools calling real DB/APIs)
- Three memory tiers (Redis state, PostgreSQL episodic, ChromaDB RAG)
- Replace stub `/agent/chat` with real LangGraph execution
- Google OAuth (swap mock login)
- LangSmith tracing
- Backtesting engine (outcome evaluation for `signal_log`)
- Prometheus + Grafana metrics
