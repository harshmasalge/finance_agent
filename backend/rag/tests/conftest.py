"""Fixtures: an isolated RAG data dir with a small synthetic annual-report PDF."""
import importlib
from pathlib import Path

import pytest


def make_pdf(path: Path, n_pages: int = 4) -> None:
    """Synthetic annual report: running header/footer, headings, body text and a table."""
    import pymupdf
    doc = pymupdf.open()
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 30), "Acme Bank Limited | Integrated Annual Report 2025-26", fontsize=8)
        page.insert_text((280, 825), f"{i + 1}", fontsize=8)
        page.insert_text((40, 90), f"Section {i + 1} Overview" if i != 2 else "Asset Quality", fontsize=18)
        y = 130
        body = (f"Page {i + 1} discusses the bank's retail franchise and branch expansion in tier two cities. "
                "Deposits grew steadily across savings and current accounts during the year. ") * 3
        if i == 2:
            body = ("The gross non-performing assets ratio stood at 1.24 percent as at March 31, 2026, "
                    "compared with 1.33 percent a year earlier, while the net NPA ratio was 0.33 percent. ") * 2
        for line_start in range(0, len(body), 95):
            page.insert_text((40, y), body[line_start:line_start + 95], fontsize=10)
            y += 14
        if i == 1:
            # a simple ruled table
            x0, y0, cw, rh = 40, 400, 150, 20
            rows = [["Metric", "FY26", "FY25"], ["Net profit (crore)", "67,347", "60,812"], ["CASA ratio", "38.2%", "39.0%"]]
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    rect = pymupdf.Rect(x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh)
                    page.draw_rect(rect, color=(0, 0, 0), width=0.8)
                    page.insert_text((rect.x0 + 4, rect.y1 - 6), val, fontsize=9)
    doc.save(str(path))


@pytest.fixture()
def rag_env(tmp_path, monkeypatch):
    """Point the RAG config at a temp data dir (embedded Chroma) and seed one document."""
    import json
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RAG_CHROMA_MODE", "embedded")
    from backend.rag import config
    importlib.reload(config)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"documents": [{
        "doc_id": "ACME-AR-FY26", "ticker": "ACME.NS", "company": "Acme Bank", "doc_type": "annual_report",
        "fiscal_year": "FY26", "title": "Acme Bank Annual Report FY26", "source_url": "https://example.com/ar.pdf"}]}))
    monkeypatch.setattr(config, "SEED_PATH", seed)
    pdf_dir = tmp_path / "corpus" / "pdfs"
    pdf_dir.mkdir(parents=True)
    make_pdf(pdf_dir / "ACME-AR-FY26.pdf")
    from backend.rag import manifest, store, retrieval
    docs = manifest.load_manifest()
    docs[0].update(local_path="corpus/pdfs/ACME-AR-FY26.pdf", status="downloaded")
    manifest.save_manifest(docs)
    store.reset_cache()
    retrieval.invalidate()
    yield config
    store.reset_cache()
    retrieval.invalidate()
    monkeypatch.undo()
    importlib.reload(config)
