"""Best-effort downloader for the curated corpus.

Plain HTTPS GETs only, with an honest User-Agent and a robots.txt check. Anything that is
refused (HTTP error, non-PDF response, robots disallow) is recorded with its reason in
`data/corpus/MANUAL_DOWNLOADS.md` so a human can fetch it from the investor-relations page
and drop it into `data/corpus/pdfs/<doc_id>.pdf` (ingest picks it up on the next run).

Usage:  python -m backend.rag.download [--only DOC_ID ...] [--force]
"""
from __future__ import annotations

import argparse
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import requests

from backend.rag import config
from backend.rag.manifest import load_manifest, save_manifest, sha256_file

USER_AGENT = "FinSightAI-corpus/1.0 (research assistant; python-requests)"
_robots_cache: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}


def robots_allows(url: str) -> bool:
    """True unless the host's robots.txt explicitly disallows this URL (unreachable robots = allowed)."""
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", timeout=15, headers={"User-Agent": USER_AGENT})
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            _robots_cache[base] = rp
        except requests.RequestException:
            _robots_cache[base] = None
    rp = _robots_cache[base]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def local_pdf_path(doc_id: str) -> Path:
    """Where a document's PDF lives on disk."""
    return config.PDF_DIR / f"{doc_id}.pdf"


def download_doc(doc: Dict, force: bool = False, timeout: int = 120) -> Dict:
    """Download one manifest document in place; returns the updated doc dict."""
    dest = local_pdf_path(doc["doc_id"])
    now = datetime.now(timezone.utc).isoformat()
    if dest.exists() and not force:  # idempotent: also covers manual drops
        doc.update(local_path=str(dest.relative_to(config.DATA_DIR)), sha256=sha256_file(dest), error=None, updated_at=now)
        if doc["status"] in ("pending", "failed_download"):
            doc["status"] = "downloaded"
        return doc
    url = doc.get("source_url")
    try:
        if not url:
            raise RuntimeError("no source_url in manifest")
        if not robots_allows(url):
            raise RuntimeError("disallowed by robots.txt")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": USER_AGENT}) as r:
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} from {urlsplit(url).netloc}")
            with open(tmp, "wb") as f:
                for block in r.iter_content(1 << 16):
                    f.write(block)
        if tmp.read_bytes()[:5] != b"%PDF-":
            tmp.unlink(missing_ok=True)
            raise RuntimeError("response is not a PDF")
        tmp.replace(dest)
        doc.update(local_path=str(dest.relative_to(config.DATA_DIR)), sha256=sha256_file(dest),
                   status="downloaded", error=None, updated_at=now)
    except Exception as e:  # record and move on (best effort)
        doc.update(status="failed_download", error=str(e), updated_at=now)
    return doc


def write_manual_list(docs: List[Dict], path: Optional[Path] = None) -> None:
    """Markdown checklist of documents that need a manual download."""
    path = Path(path or config.CORPUS_DIR / "MANUAL_DOWNLOADS.md")
    failed = [d for d in docs if d["status"] == "failed_download"]
    lines = ["# Manual downloads needed", "",
             "Download each PDF from the investor-relations page and save it as `data/corpus/pdfs/<doc_id>.pdf`, "
             "then run `python -m backend.rag.download && python -m backend.rag.ingest`.", ""]
    lines += [f"- [ ] `{d['doc_id']}` — {d.get('title')} — page: {d.get('page_url')} — reason: {d.get('error')}" for d in failed]
    if not failed:
        lines.append("Nothing outstanding.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(only: Optional[List[str]] = None, force: bool = False) -> List[Dict]:
    """Download every (or the selected) manifest document; persists after each file."""
    docs = load_manifest()
    for doc in docs:
        if only and doc["doc_id"] not in only:
            continue
        t = time.time()
        download_doc(doc, force=force)
        print(f"{doc['doc_id']:<22} {doc['status']:<16} {time.time() - t:5.1f}s {doc.get('error') or ''}")
        save_manifest(docs)
    write_manual_list(docs)
    return docs


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="doc_ids to download")
    ap.add_argument("--force", action="store_true", help="re-download even if the file exists")
    a = ap.parse_args()
    run(a.only, a.force)
