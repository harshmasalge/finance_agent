# RAG knowledge backbone — integration steps (for the lead)

Everything below touches protected files, so it is written as exact snippets to apply at merge time.
Branch: `feat/rag`. New code lives only in `backend/rag/`, `frontend/src/components/KnowledgeBase.tsx`
and `frontend/src/components/kb/`.

## 0. Dependencies + data
```bash
pip install -r backend/requirements.txt        # adds pymupdf, sentence-transformers, chromadb, rank_bm25, pyyaml
python -m backend.rag.download                  # fetch PDFs listed in backend/rag/manifest_seed.json -> data/corpus/pdfs
python -m backend.rag.ingest --budget 3600      # extract -> chunk -> embed (resumable; re-run until "ALL DONE")
python -m backend.rag.benchmark                 # writes data/benchmarks/rag_latest.json
```
`data/` is git-ignored (PDFs, page/chunk caches, the Chroma index). Chroma: with the docker-compose
service up it uses `CHROMA_URL` (default `http://localhost:8000`); otherwise it falls back to an embedded
`PersistentClient` in `data/chroma`. Force either with `RAG_CHROMA_MODE=http|embedded`.
**Note:** if you switch to the docker Chroma, run the ingest once more so vectors are written there
(chunks are cached, so only the embedding step re-runs). The first run downloads `BAAI/bge-small-en-v1.5`
(~130 MB) from Hugging Face.

## 1. Register the router — `backend/main.py`
```python
from backend.rag.router import router as kb_router
...
app.include_router(kb_router)
```
No DB tables (state lives in `data/corpus/manifest.json`).

## 2. Give the Research Agent the tool with evidence prefix `F` — `backend/agent/sub_agents.py`
`track_tools` takes one prefix per call, so `_run_agent` needs an optional extra tool group:
```python
from backend.rag.tool import search_filings

def _run_agent(name: str, prefix: str, funcs: List[Callable], prompt: str, state: AgentState,
               extra: Optional[List[Tuple[str, List[Callable]]]] = None) -> Dict:
    evidence: List[Dict] = []
    tools = track_tools(funcs, prefix=prefix, agent=name, sink=evidence)
    for extra_prefix, extra_funcs in extra or []:
        tools += track_tools(extra_funcs, prefix=extra_prefix, agent=name, sink=evidence)
    ...
```
(ids stay unique because the counter is the shared `len(sink)`, e.g. R1, R2, F3, R4.)

In `research_node`, for the non-`ideas` branch append to `task`:
```python
"Also call search_filings(ticker, query) 1-2 times per ticker for what the company itself reports in its "
"annual report / earnings calls (e.g. 'management guidance and outlook', 'asset quality GNPA NNPA' for banks, "
"'deal wins TCV and margin' for IT). Quote figures exactly as written in a passage and cite its F-id. "
"If it returns available=false, note 'no filings indexed' as a data gap — do not guess.\n"
```
and pass the tool:
```python
out = _run_agent("Research Agent", "R", [...existing...], prompt, state, extra=[("F", [search_filings])])
```
The output already contains `"ticker"` (normalised to `XXX.NS`), as the evidence contract requires.
Passages are capped at 1,500 chars and k ≤ 10, so with k=5 one call adds at most ~2k tokens.

## 3. Sources panel — render a filings passage
`frontend/src/components/advisor/evidence.ts`:
```ts
TOOL_LABELS.search_filings = 'Company filings';          // add to the TOOL_LABELS object
SOURCE_LABELS.search_filings = 'Annual report / earnings-call transcript (PDF)';
```
`frontend/src/components/advisor/EvidencePanel.tsx`, at the top of `OutputView` right after the
`available === false` block:
```tsx
import FilingPassages, { isFilingsOutput } from '../kb/FilingPassages';
...
if (isFilingsOutput(output)) return <FilingPassages output={output} />;
```
Each passage shows document title, type badge, page, section, the quoted text and an **Open PDF**
link (`${API_URL}/kb/files/{doc_id}#page={page}`) that opens the PDF at the cited page. Agent
colour: F items belong to the Research Agent, so the existing `AGENT_TONE` applies.

## 4. Nav entry + page — `frontend/src/App.tsx`
```tsx
import { Library } from 'lucide-react';
import KnowledgeBase from './components/KnowledgeBase';
// Tab union: add 'kb'
{ id: 'kb', label: 'Knowledge base', icon: <Library className="h-[18px] w-[18px]" /> },
// in the tab switch:
{tab === 'kb' && <KnowledgeBase />}
```
No new npm dependencies (uses lucide-react + the existing UI kit/tokens; light and dark themes).

## 5. Eval agent
The benchmark file `data/benchmarks/rag_latest.json` has `retrieval.modes.{hybrid,bm25,vector}.strict`
(`recall@1`, `recall@5`, `mrr`), `tables.{passed,checked}` and `ingest_speed`; `GET /kb/benchmark` serves it.

## 6. Scaling to NIFTY 50
Add entries to `backend/rag/manifest_seed.json` (`doc_id, ticker, company, doc_type, fiscal_year, period,
title, source_url, page_url`), then `POST /kb/ingest {"download": true}` (or the CLI). Downloads and
ingest are idempotent (sha256); unchanged documents are skipped, changed PDFs are re-processed, and a
chunker change re-embeds only the chunks whose text changed. Sites that refuse plain downloads are listed
in `data/corpus/MANUAL_DOWNLOADS.md` with their page URL.
