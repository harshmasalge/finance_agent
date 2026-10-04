# Evals - integration steps for the lead

No protected file was edited. Apply these at merge time.

## 1. Backend: register the router (`backend/main.py`)
```python
from evals.router import router as evals_router
...
app.include_router(evals_router)
```
`evals/` lives at the repo root (next to `backend/`). docker-compose mounts `.:/app`, so it is importable as
`evals.*` in the container. If the image is ever built with only `backend/` copied, also `COPY evals/ ./evals/`.

Endpoints (all read-only, no DB tables, no LLM):
- `GET /evals/runs` - saved runs with summary metrics, newest first
- `GET /evals/runs/{run_id}` - one run with per-case checks
- `GET /evals/backtest/latest[?include_observations=true]`
- `GET /evals/rag/latest` - `{available:false,message}` until `data/benchmarks/rag_latest.json` exists, else `{available:true,data}`

Env overrides (optional): `EVALS_RESULTS_DIR` (default `evals/results`), `RAG_BENCHMARK_PATH`
(default `data/benchmarks/rag_latest.json`).

## 2. Frontend: nav entry (`frontend/src/App.tsx`)
```tsx
import { FlaskConical } from 'lucide-react';            // add to the existing lucide import
import Evaluation from './components/Evaluation';

type Tab = 'dashboard' | 'portfolio' | 'advisor' | 'alerts' | 'evals';

// nav items, after 'alerts':
{ id: 'evals', label: 'Evaluation', icon: <FlaskConical className="h-[18px] w-[18px]" /> },

// <main> body:
{tab === 'evals' && <Evaluation />}
```
New files: `frontend/src/components/Evaluation.tsx`, `frontend/src/components/evaluation/types.ts`.
No new npm dependencies (uses recharts, lucide-react, `components/ui.tsx`, `lib/api.ts`, `lib/theme.tsx`).

## 3. Requirements
`backend/requirements.txt`: `pyyaml>=6.0` added (dataset loader). `yfinance`, `pandas` already present.

## 4. RAG benchmark
The RAG card renders whatever numeric fields `rag_latest.json` contains (recall@k, MRR, ...), so no
change is needed when its shape settles. Nothing to wire beyond the RAG agent writing that file.

## 5. Optional
- `.gitignore` already has `evals/cache/` (downloaded prices) on this branch.
- CI: `python -m pytest evals/tests -q` (55 tests, ~3 s, offline).
