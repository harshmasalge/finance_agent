"""Retrieval + extraction benchmark for the filings corpus.

* Retrieval: every question in `benchmark_qa.yaml` is run through hybrid, BM25-only and
  vector-only search (ticker-filtered, k=5) -> recall@1, recall@5, MRR, p50/p95 latency.
  `strict` = hit (doc_id, page) is one of the hand-verified locations; `lenient` additionally
  accepts any hit chunk that contains every answer key string.
* Table extraction spot check: 10 tables whose cells were verified against the raw PDF text;
  a table passes when one markdown row holds the row label and every expected value in order.
* Ingest speed: extraction pages/sec from the manifest timings, plus a fresh embedding
  throughput measurement (chunks/sec) on 128 real chunks.

Writes data/benchmarks/rag_latest.json.  Usage: python -m backend.rag.benchmark [--no-speed]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from backend.rag import config
from backend.rag.ingest import clean_table_md, pages_path, read_jsonl
from backend.rag.manifest import load_manifest

QA_PATH = Path(__file__).with_name("benchmark_qa.yaml")
K = 5

# (doc_id, page, row label, expected cell values in order) - verified against page.get_text() of the PDF
TABLE_CHECKS = [
    ("ICICIBANK-MDA-FY26", 4, "Net interest income", ["811.65", "880.75", "8.5"]),
    ("ICICIBANK-MDA-FY26", 4, "Net interest margin", ["4.32", "4.32"]),
    ("ICICIBANK-MDA-FY26", 15, "Advances", ["13,417.66", "15,538.93"]),
    ("ICICIBANK-MDA-FY26", 7, "Advances", ["12,954.29", "14,216.34", "9.7%"]),
    ("TECHM-AR-FY26", 599, "Salaries, wages and bonus", ["280,106", "273,980"]),
    ("TECHM-AR-FY26", 599, "Interest expense on lease liability", ["1,151", "655"]),
    ("SBIN-AR-FY26", 243, "Opening balance of AUCA", ["1,71,433.33", "1,75,202.14"]),
    ("SBIN-AR-FY26", 354, "Number of Equity Shares issued during the year", ["30,59,97,552", "8,100"]),
    ("TCS-AR-FY26", 150, "WEP", ["12,62,313", "87.0"]),
    ("HDFCBANK-AR-FY26", 403, "Weighted average residual maturity", ["9.07", "9.51"]),
]


def load_questions(path: Optional[Path] = None) -> List[Dict]:
    """Benchmark questions from the YAML file."""
    return yaml.safe_load(Path(path or QA_PATH).read_text(encoding="utf-8"))["questions"]


def is_relevant(hit: Dict, q: Dict, lenient: bool = False) -> bool:
    """Whether a search hit answers question `q`."""
    for e in q["expected"]:
        if hit["doc_id"] == e["doc_id"] and int(hit["page"]) in e["pages"]:
            return True
    if lenient and q.get("keys"):
        text = hit["text"].lower()
        return all(k.lower() in text for k in q["keys"])
    return False


def score_ranks(ranks: List[Optional[int]]) -> Dict:
    """recall@1 / recall@5 / MRR from 1-based first-relevant ranks (None = miss)."""
    n = len(ranks) or 1
    return {"recall@1": round(sum(1 for r in ranks if r == 1) / n, 3),
            "recall@5": round(sum(1 for r in ranks if r and r <= K) / n, 3),
            "mrr": round(sum(1.0 / r for r in ranks if r) / n, 3)}


def run_retrieval(questions: List[Dict], modes=("hybrid", "bm25", "vector")) -> Dict:
    """Run every question in every mode; returns metrics + per-question detail."""
    from backend.rag.retrieval import search
    out: Dict = {"modes": {}, "questions": []}
    detail = {q["id"]: {"id": q["id"], "ticker": q["ticker"], "question": q["question"]} for q in questions}
    for mode in modes:
        strict, lenient, lat = [], [], []
        for q in questions:
            t0 = time.perf_counter()
            hits = search(q["question"], ticker=q["ticker"], k=K, mode=mode)
            lat.append((time.perf_counter() - t0) * 1000)
            rs = next((i + 1 for i, h in enumerate(hits) if is_relevant(h, q)), None)
            rl = next((i + 1 for i, h in enumerate(hits) if is_relevant(h, q, lenient=True)), None)
            strict.append(rs)
            lenient.append(rl)
            detail[q["id"]][mode] = {"rank": rs, "rank_lenient": rl,
                                     "top": [f"{h['doc_id']}#p{h['page']}" for h in hits[:3]]}
        lat_sorted = sorted(lat)
        out["modes"][mode] = {"strict": score_ranks(strict), "lenient": score_ranks(lenient),
                              "latency_ms_p50": round(statistics.median(lat), 1),
                              "latency_ms_p95": round(lat_sorted[int(0.95 * (len(lat_sorted) - 1))], 1)}
    out["questions"] = list(detail.values())
    return out


def _row_matches(md: str, label: str, values: List[str]) -> bool:
    for row in md.splitlines():
        cells = [c.strip().strip("*` ").strip() for c in row.strip("|").split("|")]
        if not any(label.lower() in c.lower() for c in cells):
            continue
        idx = 0
        for c in cells:
            if idx < len(values) and values[idx] in c:
                idx += 1
        if idx == len(values):
            return True
    return False


def run_table_checks() -> Dict:
    """Spot-check table extraction against hand-verified cells."""
    docs = {d["doc_id"]: d for d in load_manifest()}
    results = []
    for doc_id, page, label, values in TABLE_CHECKS:
        d = docs.get(doc_id)
        ok, reason = False, "document not ingested"
        if d and d.get("ingested_sha256"):
            pg = next((p for p in read_jsonl(pages_path(doc_id, d["ingested_sha256"])) if p["page"] == page), None)
            if pg is None:
                reason = "page missing"
            elif not pg["tables"]:
                reason = "no table detected on page"
            else:
                ok = any(_row_matches(clean_table_md(t["md"]), label, values) for t in pg["tables"])
                reason = "" if ok else "row not reconstructed"
        results.append({"doc_id": doc_id, "page": page, "row": label, "values": values, "ok": ok, "reason": reason})
    return {"checked": len(results), "passed": sum(r["ok"] for r in results), "results": results}


def run_speed(n_chunks: int = 128) -> Dict:
    """Extraction pages/sec (manifest timings) and a fresh embedding-throughput measurement."""
    docs = [d for d in load_manifest() if d.get("extract_seconds") and d.get("pages")]
    pages = sum(d["pages"] for d in docs)
    secs = sum(d["extract_seconds"] for d in docs)
    out = {"extract_pages": pages, "extract_seconds": round(secs, 1),
           "extract_pages_per_sec": round(pages / secs, 2) if secs else None}
    from backend.rag.ingest import chunks_path, index_text
    from backend.rag.store import embed_passages, embedder_name
    sample: List[str] = []
    for d in docs:
        sample += [index_text(c) for c in read_jsonl(chunks_path(d["doc_id"]))[:n_chunks]]
        if len(sample) >= n_chunks:
            break
    sample = sample[:n_chunks]
    if sample:
        embed_passages(sample[:8])  # warm-up / model load
        t0 = time.perf_counter()
        embed_passages(sample, batch_size=64)
        dt = time.perf_counter() - t0
        out.update(embed_chunks=len(sample), embed_seconds=round(dt, 2),
                   embed_chunks_per_sec=round(len(sample) / dt, 2), embedding_model=embedder_name())
    return out


def corpus_summary() -> Dict:
    """Document / page / chunk / table totals for the report."""
    docs = load_manifest()
    ok = [d for d in docs if d.get("status") == "indexed"]
    return {"documents": len(docs), "indexed": len(ok), "pages": sum(d.get("pages") or 0 for d in ok),
            "chunks": sum(d.get("chunks") or 0 for d in ok), "tables": sum(d.get("tables") or 0 for d in ok),
            "scanned_pages": sum(len(d.get("scanned_pages") or []) for d in ok),
            "companies": sorted({d["ticker"] for d in ok})}


def run(speed: bool = True) -> Dict:
    """Run the full benchmark and write data/benchmarks/rag_latest.json."""
    qs = load_questions()
    res = {"generated_at": datetime.now(timezone.utc).isoformat(), "k": K, "n_questions": len(qs),
           "embedding_model": config.EMBED_MODEL, "chunk_tokens": config.CHUNK_TOKENS,
           "corpus": corpus_summary(), "retrieval": run_retrieval(qs), "tables": run_table_checks()}
    if speed:
        res["ingest_speed"] = run_speed()
    config.BENCH_DIR.mkdir(parents=True, exist_ok=True)
    config.BENCH_PATH.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-speed", action="store_true")
    r = run(speed=not ap.parse_args().no_speed)
    for m, v in r["retrieval"]["modes"].items():
        print(f"{m:<7} strict {v['strict']}  lenient {v['lenient']}  p50 {v['latency_ms_p50']}ms")
    print(f"tables {r['tables']['passed']}/{r['tables']['checked']}")
    for q in r["retrieval"]["questions"]:
        if q["hybrid"]["rank"] != 1:
            print(f"  {q['id']:<9} hybrid rank={q['hybrid']['rank']} lenient={q['hybrid']['rank_lenient']} top={q['hybrid']['top']}")
    if "ingest_speed" in r:
        print(r["ingest_speed"])
