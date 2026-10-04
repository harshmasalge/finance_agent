"""Tests for the RAG pipeline: manifest idempotency, extraction/chunking, hybrid retrieval, tool shape."""
import json

import pytest

from backend.rag import ingest, manifest


# --------------------------------------------------------------------------- manifest
def test_manifest_merge_is_idempotent_and_keeps_runtime_state():
    seed = [{"doc_id": "X-AR-FY26", "ticker": "X.NS", "doc_type": "annual_report", "fiscal_year": "FY26",
             "title": "X AR", "source_url": "u1"}]
    once = manifest.merge(seed, [])
    once[0].update(status="indexed", chunks=12, sha256="abc")
    twice = manifest.merge(seed, once)
    assert len(twice) == 1
    assert twice[0]["status"] == "indexed" and twice[0]["chunks"] == 12 and twice[0]["sha256"] == "abc"
    # seed metadata wins, hand-added docs are kept
    seed[0]["source_url"] = "u2"
    extra = {"doc_id": "Y-AR-FY26", "ticker": "Y.NS", "status": "indexed"}
    three = manifest.merge(seed, twice + [extra])
    assert [d["doc_id"] for d in three] == ["X-AR-FY26", "Y-AR-FY26"]
    assert three[0]["source_url"] == "u2" and three[0]["status"] == "indexed"


def test_manifest_save_load_roundtrip(tmp_path):
    p = tmp_path / "m.json"
    manifest.save_manifest([{"doc_id": "A", "status": "pending"}], p)
    assert manifest.load_manifest(p, use_seed=False) == [{"doc_id": "A", "status": "pending"}]
    assert json.loads(p.read_text())["version"] == 1


@pytest.mark.parametrize("raw,expected", [("tcs", "TCS.NS"), ("TCS.NS", "TCS.NS"), (" sbin ", "SBIN.NS"),
                                          ("500325.BO", "500325.BO"), ("", "")])
def test_normalize_ticker(raw, expected):
    assert manifest.normalize_ticker(raw) == expected


# --------------------------------------------------------------------------- chunking
def _page(n, blocks, tables=()):
    return {"page": n, "blocks": blocks, "tables": list(tables), "chars": 100, "images": 0, "scanned": False}


def _blk(y0, *lines, size=10.0):
    return {"y0": y0, "y1": y0 + 0.02, "lines": [{"t": t, "size": size, "bold": False} for t in lines]}


def test_chunks_respect_size_pages_sections_and_strip_headers():
    doc = {"doc_id": "D", "ticker": "D.NS", "doc_type": "annual_report", "fiscal_year": "FY26", "title": "D"}
    long_para = " ".join(f"word{i}" for i in range(700))
    pages = []
    for n in range(1, 6):
        pages.append(_page(n, [
            _blk(0.01, "Running Header Annual Report 2025-26"),          # repeated header band
            _blk(0.10, "Risk Management" if n == 3 else "Chairman Message", size=16),  # heading
            _blk(0.20, long_para if n == 1 else "Short body text about deposits and loans growth."),
            _blk(0.97, f"{n}"),                                            # page number footer
        ]))
    chunks = ingest.build_chunks(doc, pages, target=200, overlap=30)
    assert chunks, "no chunks produced"
    assert all("Running Header" not in c["text"] for c in chunks)
    assert all(c["n_tokens"] <= 200 + 40 for c in chunks)
    assert {c["page"] for c in chunks} == {1, 2, 3, 4, 5}
    assert any(c["section"] == "Risk Management" and c["page"] == 3 for c in chunks)
    p1 = [c for c in chunks if c["page"] == 1]
    assert len(p1) >= 3
    # overlap: the start of chunk 2 repeats the tail of chunk 1
    assert p1[0]["text"].split()[-1] in p1[1]["text"].split()[:40]
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)


def test_tables_are_kept_whole_as_markdown():
    doc = {"doc_id": "T", "doc_type": "annual_report"}
    md = "|Metric|FY26|\n|---|---|\n|Net profit|67,347|\n|CASA|38.2%|"
    chunks = ingest.build_chunks(doc, [_page(1, [_blk(0.2, "Financial highlights for the year")], [{"y0": 0.4, "y1": 0.5, "md": md}])])
    tab = [c for c in chunks if c["has_table"]]
    assert tab and "|Net profit|67,347|" in tab[0]["text"]


def test_scanned_pages_are_skipped():
    doc = {"doc_id": "S", "doc_type": "annual_report"}
    pg = _page(1, [])
    pg.update(scanned=True, chars=0, images=1)
    assert ingest.build_chunks(doc, [pg, _page(2, [_blk(0.3, "Real text on page two of the report.")])])[0]["page"] == 2


# --------------------------------------------------------------------------- end-to-end on a real PDF
def test_extract_real_pdf_finds_table_and_strips_header(rag_env):
    import pymupdf
    pdf = rag_env.PDF_DIR / "ACME-AR-FY26.pdf"
    with pymupdf.open(pdf) as d:
        pg = ingest.extract_page(d[1])
    assert pg["tables"], "ruled table not detected"
    assert "67,347" in pg["tables"][0]["md"]
    text = " ".join(l["t"] for b in pg["blocks"] for l in b["lines"])
    assert "67,347" not in text  # table text removed from the prose flow


@pytest.fixture()
def ingested(rag_env):
    s = ingest.run(budget=300)
    assert s["pending"] == 0
    return rag_env


def test_ingest_is_idempotent(ingested):
    d1 = manifest.load_manifest()[0]
    assert d1["status"] == "indexed" and d1["pages"] == 4 and d1["chunks"] > 0 and d1["tables"] >= 1
    from backend.rag.store import get_collection
    n = get_collection().count()
    ingest.run(budget=300)
    d2 = manifest.load_manifest()[0]
    assert get_collection().count() == n == d2["chunks"]
    assert d2["ingested_sha256"] == d1["ingested_sha256"]


def test_hybrid_search_finds_the_npa_page(ingested):
    from backend.rag.retrieval import search
    for mode in ("hybrid", "bm25", "vector"):
        hits = search("gross NPA ratio March 2026", ticker="ACME", k=3, mode=mode)
        assert hits and hits[0]["page"] == 3, mode
    assert search("gross NPA ratio", ticker="OTHER.NS") == []


def test_search_filings_output_shape(ingested):
    from backend.rag.tool import search_filings
    out = search_filings("acme", "net profit FY26", k=2)
    assert out["available"] is True and out["ticker"] == "ACME.NS" and out["query"] == "net profit FY26"
    assert 1 <= len(out["passages"]) <= 2
    keys = {"doc_id", "title", "doc_type", "fiscal_year", "page", "section", "text", "score", "url"}
    for p in out["passages"]:
        assert set(p) == keys
        assert p["url"] == f"/kb/files/{p['doc_id']}#page={p['page']}"
        assert isinstance(p["page"], int)
    json.dumps(out)  # evidence output must be JSON-serialisable
    none = search_filings("NOPE", "anything")
    assert none["available"] is False and none["passages"] == [] and none["ticker"] == "NOPE.NS"


def test_kb_router(ingested):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.rag.router import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    docs = c.get("/kb/docs").json()
    assert docs[0]["doc_id"] == "ACME-AR-FY26" and docs[0]["has_file"]
    st = c.get("/kb/stats").json()
    assert st["documents"] == 1 and st["vectors"] == st["chunks"] > 0
    r = c.get("/kb/search", params={"q": "net NPA ratio", "ticker": "ACME.NS", "k": 2}).json()
    assert r["results"] and r["results"][0]["page"] == 3
    f = c.get("/kb/files/ACME-AR-FY26")
    assert f.status_code == 200 and f.content[:4] == b"%PDF"
    assert c.get("/kb/files/../../etc").status_code == 404
    assert c.get("/kb/benchmark").json()["available"] is False
