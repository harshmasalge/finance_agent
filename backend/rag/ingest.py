"""PDF -> pages -> chunks -> vectors. Idempotent (sha256) and resumable.

Stages per manifest document:
1. extract  PyMuPDF text per page, kept as positioned blocks/lines with font size + bold flag;
            tables via `page.find_tables()` rendered to markdown (their text is removed from the
            plain-text flow so numbers are not indexed twice); pages without a text layer are
            flagged as scanned. Written incrementally to `pages/<doc_id>-<sha12>.jsonl`, so a
            run that hits its time budget resumes at the next page.
2. chunk    repeated headers/footers are stripped (lines recurring in the top/bottom 8% band of
            many pages, digits normalised), headings are detected by font size, and text is packed
            into ~CHUNK_TOKENS chunks with overlap, never crossing a page or section boundary, so
            every chunk carries an exact `page` and `section`.
3. index    chunks are embedded locally and upserted into Chroma in batches; already-present
            chunk ids are skipped, so embedding also resumes after a time-out.

A changed PDF (different sha256) invalidates its pages, chunks and vectors automatically.

Usage:  python -m backend.rag.ingest [--budget SECONDS] [--only DOC_ID ...] [--force] [--no-embed]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from backend.rag import config
from backend.rag.manifest import load_manifest, save_manifest, sha256_file

EDGE_BAND = 0.08          # top/bottom fraction of the page treated as header/footer zone
MIN_CHUNK_TOKENS = 40     # trailing fragments smaller than this merge into the previous chunk
HEADING_RATIO = 1.2       # font size vs body size to count as a heading
CHUNKER_VERSION = 3       # bump when chunking changes: docs are re-chunked from cached pages
                          # (only chunks whose text changed are re-embedded)
DOC_TYPE_LABEL = {"annual_report": "Annual Report", "earnings_call": "Earnings Call Transcript"}

_TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def count_tokens(text: str) -> int:
    """Cheap WordPiece-like token estimate (words + punctuation)."""
    return len(_TOKEN_RE.findall(text))


# ----------------------------------------------------------------------------- extract
def _table_ok(tab) -> bool:
    try:
        rows = tab.extract()
    except Exception:
        return False
    if len(rows) < 2 or tab.col_count < 2:
        return False
    cells = [c for r in rows for c in r]
    filled = sum(1 for c in cells if c not in (None, ""))
    return filled / max(len(cells), 1) >= 0.3


def extract_page(page) -> Dict:
    """One PDF page -> {page, blocks:[{y0,y1,lines:[{t,size,bold}]}], tables:[{y0,y1,md,rows,cols}], chars, images, scanned}."""
    h = page.rect.height or 1.0
    tables, boxes = [], []
    try:
        for tab in page.find_tables().tables:
            if not _table_ok(tab):
                continue
            md = tab.to_markdown(clean=True).strip()
            if md:
                x0, y0, x1, y1 = tab.bbox
                tables.append({"y0": round(y0 / h, 4), "y1": round(y1 / h, 4), "md": md,
                               "rows": tab.row_count, "cols": tab.col_count})
                boxes.append((x0 - 1, y0 - 1, x1 + 1, y1 + 1))
    except Exception:
        pass  # table detection is best-effort; text is still extracted

    def in_table(bbox) -> bool:
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes)

    blocks, chars = [], 0
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") != 0:
            continue
        lines = []
        for ln in b.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if not spans or in_table(ln["bbox"]):
                continue
            text = "".join(s["text"] for s in ln["spans"]).strip()
            size = max(s["size"] for s in spans)
            bold = all((s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower() for s in spans)
            lines.append({"t": text, "size": round(size, 1), "bold": bool(bold)})
            chars += len(text)
        if lines:
            blocks.append({"y0": round(b["bbox"][1] / h, 4), "y1": round(b["bbox"][3] / h, 4), "lines": lines})
    images = len(page.get_images(full=False))
    chars += sum(len(t["md"]) for t in tables)
    return {"page": page.number + 1, "blocks": blocks, "tables": tables, "chars": chars, "images": images,
            "scanned": chars < 20 and images > 0}


def pages_path(doc_id: str, sha: str) -> Path:
    """Per-document extracted pages file (sha in the name invalidates stale extractions)."""
    return config.PAGES_DIR / f"{doc_id}-{sha[:12]}.jsonl"


def chunks_path(doc_id: str) -> Path:
    """Per-document chunk file."""
    return config.CHUNKS_DIR / f"{doc_id}.jsonl"


def read_jsonl(path: Path) -> List[Dict]:
    """Read a jsonl file, tolerating a truncated last line from an interrupted run."""
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return out


def extract_document(pdf: Path, out: Path, deadline: float) -> Tuple[bool, int, float]:
    """Extract pages into `out`, resuming after the last page already written.
    Returns (finished, total_pages, seconds_spent)."""
    import pymupdf
    done = read_jsonl(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if done:  # rewrite cleanly in case the last line was truncated
        out.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in done), encoding="utf-8")
    t0 = time.time()
    with pymupdf.open(pdf) as d, open(out, "a", encoding="utf-8") as f:
        n = len(d)
        for i in range(len(done), n):
            if time.time() > deadline:
                return False, n, time.time() - t0
            f.write(json.dumps(extract_page(d[i]), ensure_ascii=False) + "\n")
            f.flush()
    return True, n, time.time() - t0


# ----------------------------------------------------------------------------- clean + chunk
_BR_RE = re.compile(r"<br\s*/?>", re.I)


def clean_table_md(md: str) -> str:
    """Undo HTML escaping that PyMuPDF's markdown export applies to cell text
    (`&amp;#45;` -> `-`, `&lt;br&gt;` line breaks -> ' / ') so numbers index as plain tokens."""
    prev = None
    while prev != md:  # entities can be escaped twice ("&amp;#45;")
        prev, md = md, html.unescape(md)
    return _BR_RE.sub(" / ", md)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text.lower())).strip()


def find_repeated_lines(pages: List[Dict], band: float = EDGE_BAND, min_share: float = 0.2) -> Set[str]:
    """Normalised lines that recur in the header/footer band of many pages."""
    counts: Counter = Counter()
    for pg in pages:
        seen = set()
        for b in pg["blocks"]:
            if b["y1"] <= band or b["y0"] >= 1 - band:
                for ln in b["lines"]:
                    seen.add(_norm(ln["t"]))
        counts.update(seen)
    threshold = max(3, int(min_share * len(pages)))
    return {t for t, c in counts.items() if c >= threshold and t}


def body_font_size(pages: List[Dict]) -> float:
    """Most common font size weighted by characters (the body text size)."""
    c: Counter = Counter()
    for pg in pages:
        for b in pg["blocks"]:
            for ln in b["lines"]:
                c[ln["size"]] += len(ln["t"])
    return c.most_common(1)[0][0] if c else 10.0


def is_heading(line: Dict, body: float) -> bool:
    """Heuristic heading test: noticeably larger than body text, short, mostly letters."""
    t = line["t"].strip()
    letters = sum(ch.isalpha() for ch in t)
    nonspace = sum(not ch.isspace() for ch in t) or 1
    return (line["size"] >= body * HEADING_RATIO and 3 <= len(t) <= 120 and letters >= 3
            and letters / nonspace >= 0.6 and len(t.split()) <= 16)


def _is_noise(line: Dict, block: Dict, repeated: Set[str]) -> bool:
    in_band = block["y1"] <= EDGE_BAND or block["y0"] >= 1 - EDGE_BAND
    if not in_band:
        return False
    n = _norm(line["t"])
    return n in repeated or bool(re.fullmatch(r"(page )?#+( of #+)?", n))


def _join_lines(lines: List[str]) -> str:
    out = ""
    for t in lines:
        if out.endswith("-") and t[:1].islower():
            out = out[:-1] + t
        else:
            out = f"{out} {t}" if out else t
    return out.strip()


def page_units(pg: Dict, body: float, repeated: Set[str], section: str) -> Tuple[List[Tuple[str, str, str]], str]:
    """Ordered (kind, text, section) units for one page; returns them and the section in force at page end."""
    items = [("block", b["y0"], b) for b in pg["blocks"]] + [("table", t["y0"], t) for t in pg["tables"]]
    items.sort(key=lambda x: x[1])
    units: List[Tuple[str, str, str]] = []
    for kind, _, it in items:
        if kind == "table":
            units.append(("table", clean_table_md(it["md"]), section))
            continue
        para: List[str] = []
        head: List[str] = []
        for ln in it["lines"]:
            if _is_noise(ln, it, repeated):
                continue
            if is_heading(ln, body):
                if para:
                    units.append(("text", _join_lines(para), section))
                    para = []
                head.append(ln["t"].strip())
                continue
            if head:
                section = _join_lines(head)[:120]
                units.append(("heading", section, section))
                head = []
            para.append(ln["t"].strip())
        if head:
            section = _join_lines(head)[:120]
            units.append(("heading", section, section))
        if para:
            units.append(("text", _join_lines(para), section))
    return units, section


def _split_text(text: str, target: int) -> List[str]:
    words = text.split()
    if count_tokens(text) <= target:
        return [text]
    out, cur = [], []
    for w in words:
        cur.append(w)
        if count_tokens(" ".join(cur)) >= target:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def _split_table(md: str, target: int) -> List[str]:
    if count_tokens(md) <= target:
        return [md]
    rows = md.splitlines()
    header, body = rows[:2], rows[2:]
    out, cur = [], list(header)
    for r in body:
        if count_tokens("\n".join(cur + [r])) > target and len(cur) > len(header):
            out.append("\n".join(cur))
            cur = list(header)
        cur.append(r)
    if len(cur) > len(header):
        out.append("\n".join(cur))
    # a single giant row (or a table without line structure) still has to fit the window
    return [p for piece in out for p in (_split_text(piece, target) if count_tokens(piece) > target * 1.3 else [piece])]


def _tail(text: str, n_tokens: int) -> str:
    words = text.split()
    out: List[str] = []
    for w in reversed(words):
        out.insert(0, w)
        if count_tokens(" ".join(out)) >= n_tokens:
            break
    return " ".join(out)


def build_chunks(doc: Dict, pages: List[Dict], target: Optional[int] = None, overlap: Optional[int] = None) -> List[Dict]:
    """Turn extracted pages into retrieval chunks with page + section metadata."""
    target = target or config.CHUNK_TOKENS
    overlap = config.CHUNK_OVERLAP if overlap is None else overlap
    repeated = find_repeated_lines(pages)
    body = body_font_size(pages)
    section = ""
    chunks: List[Dict] = []

    for pg in pages:
        if pg.get("scanned"):
            continue
        units, section_end = page_units(pg, body, repeated, section)
        if doc.get("doc_type") == "earnings_call":
            # transcripts have no real headings (cover-page lines would become bogus sections)
            label = f"{doc.get('period') or ''} earnings call".strip()
            units = [("text", t, label) for _, t, _ in units]
            section = section_end = label
        page_chunks: List[Dict] = []
        buf: List[str] = []
        carried = False  # buf currently holds only the overlap tail of the previous chunk
        content = False  # buf holds at least one text/table piece (not just headings / overlap)
        buf_sec = section
        has_table = False

        def flush(carry: bool) -> None:
            nonlocal buf, has_table, carried, content
            text = "\n".join(buf).strip()
            real = bool(text) and content
            content = False
            if real:
                page_chunks.append({"text": text, "section": buf_sec, "has_table": has_table})
            if carry and overlap and real:
                buf, carried = [_tail(text, overlap)], True
            else:
                buf, carried = [], False
            has_table = False

        for kind, text, sec in units:
            if kind == "heading":
                if content:
                    flush(carry=False)
                elif carried:
                    buf, carried = [], False
                buf_sec = sec
                buf.append(text)
                continue
            pieces = _split_table(text, target) if kind == "table" else _split_text(text, target)
            for p in pieces:
                if buf and count_tokens("\n".join(buf)) + count_tokens(p) > target:
                    flush(carry=kind == "text")
                buf.append(p)
                content = True
                has_table = has_table or kind == "table"
        flush(carry=False)
        # merge tiny trailing fragments into the previous chunk of the same section
        merged: List[Dict] = []
        for c in page_chunks:
            if merged and count_tokens(c["text"]) < MIN_CHUNK_TOKENS and merged[-1]["section"] == c["section"]:
                merged[-1]["text"] += "\n" + c["text"]
                merged[-1]["has_table"] = merged[-1]["has_table"] or c["has_table"]
            else:
                merged.append(c)
        for i, c in enumerate(merged):
            chunks.append({
                "chunk_id": f"{doc['doc_id']}:p{pg['page']}:{i}",
                "doc_id": doc["doc_id"], "ticker": doc.get("ticker", ""), "company": doc.get("company", ""),
                "doc_type": doc.get("doc_type", ""), "fiscal_year": doc.get("fiscal_year", ""),
                "title": doc.get("title", doc["doc_id"]), "page": pg["page"], "section": c["section"],
                "text": c["text"], "has_table": c["has_table"], "n_tokens": count_tokens(c["text"]),
            })
        section = section_end
    return chunks


def index_text(c: Dict) -> str:
    """Text actually embedded / BM25-indexed: document context + section + passage."""
    label = DOC_TYPE_LABEL.get(c.get("doc_type", ""), c.get("doc_type", ""))
    head = f"{c.get('company', '')} {label} {c.get('fiscal_year', '')}".strip()
    return f"{head} | {c['section']}\n{c['text']}" if c.get("section") else f"{head}\n{c['text']}"


# ----------------------------------------------------------------------------- index
def delete_doc_vectors(doc_id: str) -> None:
    """Remove a document's vectors from Chroma (used when its PDF changes)."""
    from backend.rag.store import get_collection
    try:
        get_collection().delete(where={"doc_id": doc_id})
    except Exception:
        pass


def index_chunks(chunks: List[Dict], deadline: float, batch_size: int = 64) -> Tuple[bool, int, float]:
    """Embed + upsert chunks whose id is missing from Chroma or whose stored text differs, and delete
    vectors of the document's chunks that no longer exist. Returns (finished, n_embedded_now, seconds)."""
    from backend.rag.store import embed_passages, get_collection
    col = get_collection()
    ids = [c["chunk_id"] for c in chunks]
    stored: Dict[str, str] = {}
    for d_id in {c["doc_id"] for c in chunks}:
        got = col.get(where={"doc_id": d_id}, include=["documents"])
        stored.update(zip(got["ids"], got["documents"] or [""] * len(got["ids"])))
    gone = [i for i in stored if i not in set(ids)]
    for i in range(0, len(gone), 500):
        col.delete(ids=gone[i:i + 500])
    todo = [c for c in chunks if stored.get(c["chunk_id"]) != index_text(c)]
    t0, n = time.time(), 0
    for i in range(0, len(todo), batch_size):
        if time.time() > deadline:
            return False, n, time.time() - t0
        batch = todo[i:i + batch_size]
        texts = [index_text(c) for c in batch]
        col.upsert(ids=[c["chunk_id"] for c in batch], embeddings=embed_passages(texts), documents=texts,
                   metadatas=[{"doc_id": c["doc_id"], "ticker": c["ticker"], "doc_type": c["doc_type"],
                               "fiscal_year": c["fiscal_year"], "page": int(c["page"]), "section": c["section"] or "",
                               "has_table": bool(c["has_table"])} for c in batch])
        n += len(batch)
    return True, n, time.time() - t0


# ----------------------------------------------------------------------------- driver
def _reset_doc(doc: Dict) -> None:
    for p in config.PAGES_DIR.glob(f"{doc['doc_id']}-*.jsonl"):
        p.unlink(missing_ok=True)
    chunks_path(doc["doc_id"]).unlink(missing_ok=True)
    delete_doc_vectors(doc["doc_id"])
    doc.update(ingested_sha256=None, chunks=None, pages=None, scanned_pages=[], tables=None,
               extract_seconds=None, embed_seconds=None, status="downloaded")


def process_document(doc: Dict, deadline: float, embed: bool = True, force: bool = False) -> bool:
    """Advance one document as far as the deadline allows. Returns True when it is fully done."""
    if not doc.get("local_path"):
        return True  # nothing to ingest (failed / not downloaded)
    pdf = config.DATA_DIR / doc["local_path"]
    if not pdf.exists():
        doc.update(status="failed_ingest", error=f"missing file {doc['local_path']}")
        return True
    sha = sha256_file(pdf)
    doc["sha256"] = sha
    if force or (doc.get("ingested_sha256") and doc["ingested_sha256"] != sha):
        _reset_doc(doc)
    try:
        out = pages_path(doc["doc_id"], sha)
        stale_chunks = doc.get("chunker_version") != CHUNKER_VERSION and doc.get("ingested_sha256") == sha
        if doc.get("ingested_sha256") != sha or not chunks_path(doc["doc_id"]).exists() or stale_chunks:
            if not (stale_chunks and out.exists()):  # else: pages still valid -> only re-chunk
                finished, n_pages, secs = extract_document(pdf, out, deadline)
                doc["extract_seconds"] = round((doc.get("extract_seconds") or 0) + secs, 2)
                doc["pages"] = n_pages
                if not finished:
                    doc["status"] = "extracting"
                    return False
            pages = read_jsonl(out)
            chunks = build_chunks(doc, pages)
            p = chunks_path(doc["doc_id"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks), encoding="utf-8")
            doc.update(chunks=len(chunks), scanned_pages=[pg["page"] for pg in pages if pg.get("scanned")],
                       empty_pages=[pg["page"] for pg in pages if pg["chars"] < 20 and not pg.get("scanned")],
                       tables=sum(len(pg["tables"]) for pg in pages), ingested_sha256=sha,
                       chunker_version=CHUNKER_VERSION,
                       status="extracted", error=None)
        if embed and doc["status"] != "indexed":
            chunks = read_jsonl(chunks_path(doc["doc_id"]))
            finished, _, secs = index_chunks(chunks, deadline)
            doc["embed_seconds"] = round((doc.get("embed_seconds") or 0) + secs, 2)
            if not finished:
                return False
            doc["status"] = "indexed"
        return True
    except Exception as e:
        doc.update(status="failed_ingest", error=f"{type(e).__name__}: {e}")
        return True
    finally:
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()


def run(budget: float = 150.0, only: Optional[Iterable[str]] = None, force: bool = False, embed: bool = True) -> Dict:
    """Process all (or selected) manifest documents within `budget` seconds; safe to call repeatedly."""
    deadline = time.time() + budget
    docs = load_manifest()
    only = set(only or [])
    pending = 0
    for doc in docs:
        if only and doc["doc_id"] not in only:
            continue
        if doc["status"] in ("pending", "failed_download"):
            continue
        done = process_document(doc, deadline, embed=embed, force=force)
        save_manifest(docs)
        if not done:
            pending += 1
            break
    summary = {"pending": pending, "documents": {d["doc_id"]: d["status"] for d in docs}}
    from backend.rag import retrieval
    retrieval.invalidate()
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=float, default=150.0, help="seconds to work before stopping (resumable)")
    ap.add_argument("--only", nargs="*", help="doc_ids to process")
    ap.add_argument("--force", action="store_true", help="re-extract and re-embed even if unchanged")
    ap.add_argument("--no-embed", action="store_true", help="extract + chunk only")
    a = ap.parse_args()
    s = run(a.budget, a.only, a.force, embed=not a.no_embed)
    for k, v in s["documents"].items():
        print(f"{k:<22} {v}")
    print("MORE WORK PENDING - run again" if s["pending"] else "ALL DONE")
