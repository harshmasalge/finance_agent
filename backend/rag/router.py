"""`/kb` API: corpus documents and stats, hybrid search, background ingest, PDF serving, benchmark."""
from __future__ import annotations

import json
import threading
from typing import Dict, List, Optional

from backend.app_mode import require_demo_mode
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.rag import config
from backend.rag.manifest import load_manifest, normalize_ticker

router = APIRouter(prefix="/kb", tags=["knowledge-base"])

_ingest_lock = threading.Lock()
_ingest_state: Dict = {"running": False, "last": None, "error": None}

DOC_FIELDS = ("doc_id", "ticker", "company", "doc_type", "fiscal_year", "period", "title", "pages", "chunks",
              "tables", "status", "scanned_pages", "empty_pages", "error", "source_url", "page_url", "updated_at")


def _public(doc: Dict) -> Dict:
    out = {k: doc.get(k) for k in DOC_FIELDS}
    out["has_file"] = bool(doc.get("local_path")) and (config.DATA_DIR / doc["local_path"]).exists()
    out["scanned_pages"] = out["scanned_pages"] or []
    out["empty_pages"] = out["empty_pages"] or []
    return out


@router.get("/docs")
def list_docs(ticker: Optional[str] = None) -> List[Dict]:
    """All corpus documents with pipeline status (optionally for one ticker)."""
    docs = load_manifest()
    if ticker:
        t = normalize_ticker(ticker)
        docs = [d for d in docs if d.get("ticker") == t]
    return [_public(d) for d in docs]


@router.get("/stats")
def stats() -> Dict:
    """Corpus totals, vector count and embedding/vector-store configuration."""
    docs = load_manifest()
    by_status: Dict[str, int] = {}
    for d in docs:
        by_status[d["status"]] = by_status.get(d["status"], 0) + 1
    vectors, mode = None, None
    try:
        from backend.rag.store import client_mode, get_collection
        vectors = get_collection().count()
        mode = client_mode()
    except Exception:
        pass
    ok = [d for d in docs if d.get("status") in ("extracted", "indexed")]
    return {
        "documents": len(docs), "by_status": by_status,
        "companies": sorted({d["ticker"] for d in docs}),
        "pages": sum(d.get("pages") or 0 for d in ok), "chunks": sum(d.get("chunks") or 0 for d in ok),
        "tables": sum(d.get("tables") or 0 for d in ok),
        "scanned_pages": sum(len(d.get("scanned_pages") or []) for d in ok),
        "vectors": vectors, "vector_store": mode, "embedding_model": config.EMBED_MODEL,
        "chunk_tokens": config.CHUNK_TOKENS, "ingest": dict(_ingest_state),
    }


@router.get("/search")
def kb_search(q: str = Query(..., min_length=2), ticker: Optional[str] = None, k: int = Query(5, ge=1, le=20),
              doc_type: Optional[str] = None, mode: str = Query("hybrid", pattern="^(hybrid|bm25|vector)$")) -> Dict:
    """Hybrid search; `ticker` optional (all companies when omitted)."""
    from backend.rag.retrieval import search
    hits = search(q, ticker=ticker, k=k, doc_types=[doc_type] if doc_type else None, mode=mode)
    return {"query": q, "ticker": normalize_ticker(ticker) if ticker else None, "mode": mode, "results": [
        {"doc_id": h["doc_id"], "ticker": h["ticker"], "company": h["company"], "title": h["title"],
         "doc_type": h["doc_type"], "fiscal_year": h["fiscal_year"], "page": h["page"], "section": h["section"],
         "text": h["text"], "has_table": h["has_table"], "score": h["score"], "bm25_rank": h["bm25_rank"],
         "vector_rank": h["vector_rank"], "url": f"/kb/files/{h['doc_id']}#page={h['page']}"} for h in hits]}


class IngestRequest(BaseModel):
    download: bool = False
    only: Optional[List[str]] = None
    force: bool = False


def _run_ingest(req: IngestRequest) -> None:
    from backend.rag import download, ingest
    try:
        if req.download:
            download.run(req.only)
        _ingest_state["last"] = ingest.run(budget=10 ** 9, only=req.only, force=req.force)
        _ingest_state["error"] = None
    except Exception as e:  # surfaced via /kb/stats
        _ingest_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        _ingest_state["running"] = False
        _ingest_lock.release()


@router.post("/ingest", status_code=202, dependencies=[Depends(require_demo_mode)])
def start_ingest(req: IngestRequest, background: BackgroundTasks) -> Dict:
    """Start (download +) ingest in the background; idempotent, only one run at a time."""
    if not _ingest_lock.acquire(blocking=False):
        return {"started": False, "message": "An ingest run is already in progress."}
    _ingest_state["running"] = True
    background.add_task(_run_ingest, req)
    return {"started": True}


@router.get("/files/{doc_id}")
def get_file(doc_id: str) -> FileResponse:
    """Serve a corpus PDF inline (append #page=N client-side to jump to a page)."""
    doc = next((d for d in load_manifest() if d["doc_id"] == doc_id), None)
    if not doc or not doc.get("local_path"):
        raise HTTPException(404, f"No file for document {doc_id}")
    path = (config.DATA_DIR / doc["local_path"]).resolve()
    if config.DATA_DIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, f"No file for document {doc_id}")
    return FileResponse(path, media_type="application/pdf", filename=f"{doc_id}.pdf",
                        content_disposition_type="inline")


@router.get("/benchmark")
def benchmark() -> Dict:
    """Latest retrieval benchmark (data/benchmarks/rag_latest.json)."""
    if not config.BENCH_PATH.exists():
        return {"available": False, "message": "Run `python -m backend.rag.benchmark` to generate it."}
    data = json.loads(config.BENCH_PATH.read_text(encoding="utf-8"))
    data["available"] = True
    return data
