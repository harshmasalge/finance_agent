"""`search_filings` — the RAG tool exposed to FinSight agents (evidence prefix `F`)."""
from __future__ import annotations

from typing import Dict

from backend.rag.manifest import load_manifest, normalize_ticker

MAX_K = 10
MAX_PASSAGE_CHARS = 1500


def search_filings(ticker: str, query: str, k: int = 5) -> dict:
    """
    Searches the company's official filings — the latest annual report and recent earnings-call
    transcripts of an NSE company (e.g. 'HDFCBANK.NS', 'TCS.NS') — and returns the most relevant
    passages, each with document title, fiscal year, page number and section.
    Use it for questions about strategy, management commentary and guidance, segment performance,
    risks, asset quality, capital, headcount, deals, ESG or any figure reported in the annual report.
    Write `query` as a specific natural-language question or phrase (e.g. "gross NPA ratio March 2026",
    "management outlook on deal pipeline"). Quote numbers exactly as they appear in a passage and cite
    the passage's page; if no passage answers the question, say the filings do not cover it.
    Returns available=false when no filings are indexed for the ticker.
    """
    from backend.rag.retrieval import search

    t = normalize_ticker(ticker)
    k = max(1, min(int(k or 5), MAX_K))
    docs = [d for d in load_manifest() if d.get("ticker") == t and d.get("status") in ("extracted", "indexed")]
    if not docs:
        return {"available": False, "ticker": t, "query": query, "passages": [],
                "message": f"No filings are indexed for {t}. Ask the user to add its annual report to the knowledge base."}
    hits = search(query, ticker=t, k=k)
    passages = []
    for h in hits:
        text = h["text"]
        if len(text) > MAX_PASSAGE_CHARS:
            text = text[:MAX_PASSAGE_CHARS].rsplit(" ", 1)[0] + " …"
        passages.append({
            "doc_id": h["doc_id"], "title": h["title"], "doc_type": h["doc_type"], "fiscal_year": h["fiscal_year"],
            "page": h["page"], "section": h["section"], "text": text, "score": h["score"],
            "url": f"/kb/files/{h['doc_id']}#page={h['page']}",
        })
    out: Dict = {"available": True, "ticker": t, "query": query, "passages": passages}
    if not passages:
        out["message"] = "No passage in the indexed filings matched this query."
    return out
