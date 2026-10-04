"""Hybrid retrieval over the filings corpus: BM25 (rank_bm25, exact numbers / names) +
dense vectors (Chroma, paraphrases) fused with reciprocal-rank fusion, filtered by ticker."""
from __future__ import annotations

import re
import threading
from typing import Dict, List, Optional, Tuple

from backend.rag import config
from backend.rag.ingest import chunks_path, index_text, read_jsonl
from backend.rag.manifest import load_manifest, normalize_ticker

RRF_K = 60
CANDIDATES = 40
STOPWORDS = set("""a an and are as at be by for from has have in is it its of on or that the this to was were
will with what which who how did does do during their our we you your i me my about than into over""".split())
_TOK = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")

_lock = threading.Lock()
_bm25_cache: Dict[Tuple, Tuple] = {}


def tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric tokens (numbers like 1,234.5 kept whole, commas dropped), no stopwords."""
    return [t.replace(",", "") for t in _TOK.findall(text.lower()) if t not in STOPWORDS]


def invalidate() -> None:
    """Drop cached BM25 indexes (called after ingest)."""
    with _lock:
        _bm25_cache.clear()


def _docs_for(ticker: Optional[str], doc_types: Optional[List[str]]) -> List[Dict]:
    docs = [d for d in load_manifest() if d.get("status") in ("extracted", "indexed")]
    if ticker:
        docs = [d for d in docs if d.get("ticker") == ticker]
    if doc_types:
        docs = [d for d in docs if d.get("doc_type") in doc_types]
    return docs


def _bm25_for(docs: List[Dict]):
    from rank_bm25 import BM25Okapi
    key = tuple(sorted((d["doc_id"], d.get("ingested_sha256"), d.get("chunks")) for d in docs))
    with _lock:
        if key in _bm25_cache:
            return _bm25_cache[key]
    chunks: List[Dict] = []
    for d in docs:
        chunks.extend(read_jsonl(chunks_path(d["doc_id"])))
    bm25 = BM25Okapi([tokenize(index_text(c)) for c in chunks]) if chunks else None
    with _lock:
        _bm25_cache[key] = (bm25, chunks)
    return bm25, chunks


def _vector_ranks(query: str, docs: List[Dict], n: int) -> List[str]:
    indexed = [d["doc_id"] for d in docs if d.get("status") == "indexed"]
    if not indexed:
        return []
    from backend.rag.store import embed_query, get_collection
    where = {"doc_id": indexed[0]} if len(indexed) == 1 else {"doc_id": {"$in": indexed}}
    res = get_collection().query(query_embeddings=[embed_query(query)], n_results=n, where=where, include=[])
    return res["ids"][0] if res.get("ids") else []


def search(query: str, ticker: Optional[str] = None, k: int = 5, doc_types: Optional[List[str]] = None,
           mode: str = "hybrid") -> List[Dict]:
    """Top-k chunks for `query`. mode: 'hybrid' (default), 'bm25' or 'vector'.
    Each result is the chunk dict plus `score` (fused), `bm25_rank`, `vector_rank` (1-based or None)."""
    ticker = normalize_ticker(ticker) if ticker else None
    docs = _docs_for(ticker, doc_types)
    if not docs or not query.strip():
        return []
    bm25, chunks = _bm25_for(docs)
    by_id = {c["chunk_id"]: c for c in chunks}

    bm25_ids: List[str] = []
    if bm25 is not None and mode in ("hybrid", "bm25"):
        scores = bm25.get_scores(tokenize(query))
        order = sorted(range(len(chunks)), key=lambda i: -scores[i])[:CANDIDATES]
        bm25_ids = [chunks[i]["chunk_id"] for i in order if scores[i] > 0]
    vec_ids: List[str] = []
    if mode in ("hybrid", "vector"):
        try:
            vec_ids = [i for i in _vector_ranks(query, docs, CANDIDATES) if i in by_id]
        except Exception:
            vec_ids = []  # vector store unavailable -> degrade to BM25 only

    fused: Dict[str, float] = {}
    for ranks in (bm25_ids, vec_ids):
        for r, cid in enumerate(ranks):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + r + 1)
    top = sorted(fused, key=lambda c: -fused[c])[:k]
    out = []
    for cid in top:
        c = dict(by_id[cid])
        c["score"] = round(fused[cid], 5)
        c["bm25_rank"] = bm25_ids.index(cid) + 1 if cid in bm25_ids else None
        c["vector_rank"] = vec_ids.index(cid) + 1 if cid in vec_ids else None
        out.append(c)
    return out
