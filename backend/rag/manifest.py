"""Corpus manifest: the single source of truth for which documents exist and how far each
has progressed through the pipeline (pending -> downloaded -> extracted -> indexed).

`manifest_seed.json` (committed) lists curated sources; `data/corpus/manifest.json` (git-ignored)
adds runtime fields. Merging is idempotent: re-running never duplicates documents and never
loses runtime state."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from backend.rag import config

# Fields owned by the curated seed (always refreshed from it).
SEED_FIELDS = ("ticker", "company", "doc_type", "fiscal_year", "period", "title", "source_url", "page_url")
# Runtime fields with their defaults.
RUNTIME_DEFAULTS = {"local_path": None, "sha256": None, "pages": None, "chunks": None, "scanned_pages": [],
                    "tables": None, "status": "pending", "error": None, "ingested_sha256": None,
                    "extract_seconds": None, "updated_at": None}


def sha256_file(path: Path, bufsize: int = 1 << 20) -> str:
    """Hex sha256 of a file, streamed."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(bufsize), b""):
            h.update(block)
    return h.hexdigest()


def load_seed(seed_path: Optional[Path] = None) -> List[Dict]:
    """Curated document list from the committed seed file."""
    return json.loads(Path(seed_path or config.SEED_PATH).read_text(encoding="utf-8"))["documents"]


def merge(seed_docs: List[Dict], existing: List[Dict]) -> List[Dict]:
    """Merge seed entries into an existing manifest list, keyed by doc_id. Seed metadata wins,
    runtime fields are preserved; documents not in the seed (e.g. added by hand) are kept."""
    by_id = {d["doc_id"]: dict(d) for d in existing}
    order = [d["doc_id"] for d in existing]
    for s in seed_docs:
        doc = by_id.get(s["doc_id"], {"doc_id": s["doc_id"]})
        for k in SEED_FIELDS:
            if k in s:
                doc[k] = s[k]
        for k, v in RUNTIME_DEFAULTS.items():
            doc.setdefault(k, list(v) if isinstance(v, list) else v)
        if s["doc_id"] not in by_id:
            order.append(s["doc_id"])
        by_id[s["doc_id"]] = doc
    return [by_id[i] for i in order]


def load_manifest(path: Optional[Path] = None, seed_path: Optional[Path] = None, use_seed: bool = True) -> List[Dict]:
    """Current manifest documents (seed merged in). Missing manifest file -> built from seed."""
    path = Path(path or config.MANIFEST_PATH)
    seed_path = Path(seed_path or config.SEED_PATH) if use_seed else None
    existing: List[Dict] = []
    if Path(path).exists():
        existing = json.loads(Path(path).read_text(encoding="utf-8")).get("documents", [])
    if seed_path is not None and Path(seed_path).exists():
        return merge(load_seed(seed_path), existing)
    return existing


def save_manifest(docs: List[Dict], path: Optional[Path] = None) -> None:
    """Atomically write the manifest (write temp file + rename)."""
    path = Path(path or config.MANIFEST_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "documents": docs}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def normalize_ticker(ticker: str) -> str:
    """'tcs' / 'TCS' / 'TCS.NS' -> 'TCS.NS' (BSE '.BO' suffix is kept)."""
    t = (ticker or "").strip().upper()
    if not t:
        return t
    return t if "." in t else f"{t}.NS"
