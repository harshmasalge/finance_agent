# FinSight v2 — Build contracts for the three feature agents

Base: branch `finsight-v2` @ 96461c3. Each agent works ONLY in its own clone + branch on the device shell's fast local disk (`$HOME/work/<name>`, NOT the mounted project folder, which is very slow for many small writes). The lead regularly fetches each branch into the project repo as `feat/*` (backup + review) and merges from there:

| Agent | Branch | Clone |
|---|---|---|
| RAG (knowledge backbone) | `feat/rag` | `$HOME/work/rag` |
| Review (expert review + approve) | `feat/review` | `$HOME/work/review` |
| Eval (evaluation harness) | `feat/evals` | `$HOME/work/evals` |

The lead (boss) reviews and merges in order RAG → Review → Eval and does all wiring in shared files.

## 1. Ground rules (all agents)
1. **Do not edit protected files.** If you need a change there, write the exact snippet in `INTEGRATION.md` at the root of your area and the lead applies it at merge time.
   Protected: `backend/agent/{graph,schemas,state,orchestrator,sub_agents,synthesis,utils,evidence,scoring}.py`,
   `backend/db/models.py`, `backend/db/database.py`, `backend/main.py`, `backend/routers/agent.py`,
   `frontend/src/App.tsx`, `frontend/src/lib/api.ts`, `frontend/src/components/AIChat.tsx`, `frontend/src/components/advisor/*`, `frontend/src/index.css`, `frontend/src/components/ui.tsx`.
2. **No live LLM calls** (OpenRouter credit is exhausted until it renews). Anything that calls an LLM must take an injectable model / callable so tests use fakes. Use the recorded real answers in `backend/tests/fixtures/answers.json` (AnswerPayload objects incl. evidence, scorecards, validation, steps).
3. **Backend modules**: put code in your own package (`backend/rag/`, `backend/review/`, `evals/`). DB tables go in your own `models.py` using `from backend.db.database import Base` (tables are auto-created at API startup once the lead imports your models). Expose one FastAPI `router` from `<package>/router.py`; the lead registers it.
4. **Frontend**: new components only, default-exported page components; use the existing UI kit (`components/ui.tsx`, `components/toast.tsx`), theme tokens (`bg-surface`, `text-muted`, `border-border`, `text-up/down/warn`, `bg-primary` …), and `lib/api.ts` helper `api<T>()`. Put any new TS types in your own `types.ts`. Must look right in BOTH light and dark themes. No new npm dependencies without listing them in INTEGRATION.md.
5. **Quality bar**: `python -m pytest` for your tests passes; `npx tsc -b` and `npx vite build` pass; no secrets in code; type hints + docstrings on public functions; small focused commits on your branch ending with the attribution lines:
   ```
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   Claude-Session: https://claude.ai/code/session_012ayvcQYJgoh4R9ryakmfj7
   ```
   Commit author: `-c user.name="Harsh" -c user.email="harshmasalge594@gmail.com"`.
6. **Where to run things**: use the device shell. Python venv with all backend deps: `$HOME/venv` (add packages there, and to `backend/requirements.txt` in your branch). Use SQLite (`POSTGRES_URL=sqlite:///...`) and `fakeredis` for tests — see `$HOME/smoke/test_api.py` for the pattern. For frontend checks copy your clone's `frontend/` to a scratch dir under `$HOME` and run `npm install` there (the Windows `node_modules` won't work on Linux). Never write scratch files inside the repo.
7. Finish with a short `REPORT.md` in your area: what was built, how to run it, test results, known gaps, and the INTEGRATION steps.

## 2. Shared data contracts

**Evidence item** (one per tool call; already used everywhere):
```json
{"id": "F3", "agent": "Research Agent", "tool": "search_filings", "input": {...}, "output": {...}, "created_at": "ISO-8601"}
```
Id prefixes: `R` research, `S` sentiment, `P` portfolio/risk, `C` scorecard (existing). **New:** `F` = filings passages (RAG), `A` = analyst notes (Review). Ticker-specific outputs MUST contain `"ticker"`.

**Answer payload** = `AnswerPayload` in `frontend/src/lib/api.ts` / saved in `chat_messages.payload` (`answer`, `evidence`, `scorecards`, `validation`, `steps`, `intent`, `tickers`, `duration_s`, `llm`). `answer` is `FinalAnswer` from `backend/agent/schemas.py`.

**Demo universe**: HDFCBANK.NS, TCS.NS, ICICIBANK.NS, SBIN.NS, TECHM.NS (pipeline must scale to all NIFTY 50 later).

## 3. Agent briefs

### RAG agent — `backend/rag/`, `frontend/src/components/KnowledgeBase.tsx`
- `data/corpus/manifest.json` (+ `backend/rag/manifest_seed.json` committed): per document `doc_id, ticker, company, doc_type (annual_report|earnings_call), fiscal_year, source_url, local_path, sha256, pages, status`.
- `backend/rag/download.py`: best-effort download of the latest annual report (+ up to 2 earnings-call transcripts) per demo company from official investor-relations pages; record failures with a reason in a `MANUAL_DOWNLOADS.md` list. Respect robots/terms; plain HTTPS GETs only.
- `backend/rag/ingest.py`: PyMuPDF text per page; tables → markdown (`page.find_tables()`); strip repeated headers/footers; detect scanned pages (no text) and flag them; chunk by heading ~800 tokens with overlap, keep `page`, `section`; idempotent via sha256.
- Embeddings: local `sentence-transformers` (`BAAI/bge-small-en-v1.5` preferred, fallback `all-MiniLM-L6-v2`) — no API calls. Vector store: Chroma — HTTP client to `CHROMA_URL` (docker, default `http://localhost:8000`) with fallback to embedded `PersistentClient("data/chroma")`. Hybrid retrieval (BM25 via `rank_bm25` + vector, reciprocal-rank fusion), filter by ticker, top-k=5.
- Tool for agents: `backend/rag/tool.py` → `search_filings(ticker: str, query: str, k: int = 5) -> dict` returning `{"available": bool, "ticker", "query", "passages": [{"doc_id","title","doc_type","fiscal_year","page","section","text","score","url"}]}` (`url` = `/kb/files/{doc_id}#page={page}`). Docstring written for an LLM tool.
- Router `/kb`: `GET /kb/docs`, `GET /kb/stats`, `GET /kb/search?ticker=&q=&k=`, `POST /kb/ingest` (background), `GET /kb/files/{doc_id}` (serves the PDF).
- Benchmark: `backend/rag/benchmark_qa.yaml` (~30 questions with expected `doc_id` + `page`, written by reading the PDFs) and `backend/rag/benchmark.py` → recall@1/@5, MRR, table-extraction spot check (10 tables), ingest pages/sec; writes `data/benchmarks/rag_latest.json`.
- UI `KnowledgeBase.tsx`: documents table (company, type, FY, pages, chunks, status, scanned-page warnings), corpus stats, a search box showing passages with page + "Open PDF" link, benchmark summary.
- INTEGRATION.md must give: tool registration for the Research Agent + prompt lines, evidence prefix `F`, how the Sources panel should render a passage, nav entry.

### Review agent — `backend/review/`, `frontend/src/components/review/`, `frontend/src/components/ResearchNotes.tsx`
- Tables: `answer_status(message_id PK, status draft|approved|rejected, current_version, updated_at)`, `answer_revisions(id, message_id, version, answer JSON, scorecards JSON, author agent|analyst, feedback_id, created_at)`, `feedback(id, message_id, correction_text, category fact|judgement|weighting|format, target, before JSON, after JSON, change_log JSON, agent_response, accepted bool, created_at)`, `research_notes(id, message_id, version, ticker, title, verdict, body JSON, published_at, connector_status, connector_response)`. Version 1 = the original payload (create lazily).
- Correction Agent `backend/review/correction.py`: input = current FinalAnswer + evidence + scorecards + correction text; output Pydantic `CorrectionResult {category, accepted: bool, pushback: str|None, revised_answer: FinalAnswer, change_log: [{path, before, after, reason}], scorecard_overrides: {factor: weight|null}}`. If the correction contradicts cited evidence, `accepted=false` and `pushback` cites the evidence id. Weighting corrections → recompute scorecards deterministically (needs a weights-override parameter on `scoring.score_ticker` → put the patch in INTEGRATION.md; you may implement a local wrapper meanwhile). LLM injected; tests use a fake LLM.
- Connector `backend/review/connector.py`: `ResearchNotesConnector.publish(note) -> {status, id}`; target URL from `NOTES_API_URL` (default: our own `/research-notes` endpoint), idempotent on `(message_id, version)`, records response; draft/rejected answers can never be published.
- Router: `GET /review/{message_id}`, `POST /review/{message_id}/correct {text, target?}`, `POST /review/{message_id}/approve {version?}`, `POST /review/{message_id}/reject`, `GET /review/feedback/export.jsonl`, `GET /research-notes`, `POST /research-notes` (the "platform" endpoint), `GET /research-notes/{id}`.
- Learning loop: `backend/review/notes.py::analyst_notes_for(tickers) -> list[evidence items with prefix A]` from accepted feedback — INTEGRATION.md explains how synthesis should include them.
- UI: `review/ReviewBar.tsx` (status chip Draft/Approved/Rejected, version switcher, "Correct" input, Approve/Reject buttons with confirm), `review/DiffView.tsx` (claim-level red/green diff + change log + pushback message), `ResearchNotes.tsx` page (list + detail, export Markdown). INTEGRATION.md: where ReviewBar mounts under each answer in AnswerView, nav entry.

### Eval agent — `evals/`, `frontend/src/components/Evaluation.tsx`
- `evals/dataset.yaml`: ~25 cases `{id, question, expected_intent, expected_tickers, expected_answer_type, must_include: [...], must_not_include: [...], notes}` covering all intents incl. follow-ups and tricky names (e.g. "policy bazaar" → POLICYBZR.NS, "L&T" → LT.NS).
- `evals/metrics.py` (pure functions, unit-tested): routing accuracy, ticker F1, schema validity (FinalAnswer parses), citation coverage (claims with ≥1 citation), citation validity (ids exist), number-grounding (numbers in a claim appear in its cited evidence output, tolerant to rounding/₹/commas/%), forbidden-content check (non-NSE tickers), verdict determinism (scorecard re-run on same evidence), latency, token/cost if present.
- `evals/run.py`: `--mode live` (calls `/agent/chat` in-process; only when credits exist) and `--mode replay --fixtures backend/tests/fixtures/answers.json` (no LLM). Results → `evals/results/<run_id>.json` (+ summary). Optional LLM-judge faithfulness behind `--judge` flag with injectable LLM.
- `evals/backtest.py`: point-in-time scorecard backtest on price-based factors only (trend, momentum, RSI, 3-month return) using `backend.agent.scoring.score_ticker` with technical outputs computed from historical windows; NIFTY 50 universe, monthly rebalance over the last 12 months; report hit rate and average 30-day excess return vs ^NSEI per verdict bucket. Must be clear in the report that fundamentals/sentiment are excluded (no point-in-time data).
- Read RAG benchmark from `data/benchmarks/rag_latest.json` if present.
- Router `/evals`: `GET /evals/runs`, `GET /evals/runs/{id}`, `GET /evals/backtest/latest`.
- UI `Evaluation.tsx`: KPI tiles (routing acc, citation coverage, grounding, checker pass, p50/p95 latency), per-case table with pass/fail drill-down, backtest table/chart (follow the dataviz rules already used: single axis, no dual-axis), RAG benchmark card.
