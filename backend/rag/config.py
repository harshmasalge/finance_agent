"""Paths and settings for the RAG pipeline (all overridable via environment variables)."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", REPO_ROOT / "data"))
CORPUS_DIR = DATA_DIR / "corpus"
PDF_DIR = CORPUS_DIR / "pdfs"
PAGES_DIR = CORPUS_DIR / "pages"      # per-document extracted pages (jsonl, resumable)
CHUNKS_DIR = CORPUS_DIR / "chunks"    # per-document chunks (jsonl)
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
SEED_PATH = Path(__file__).with_name("manifest_seed.json")
BENCH_DIR = DATA_DIR / "benchmarks"
BENCH_PATH = BENCH_DIR / "rag_latest.json"
CHROMA_PATH = DATA_DIR / "chroma"

CHROMA_URL = os.getenv("CHROMA_URL", "http://localhost:8000")
COLLECTION = os.getenv("RAG_COLLECTION", "filings")
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_FALLBACK = "sentence-transformers/all-MiniLM-L6-v2"
# bge models are trained with this instruction prefix on the query side only.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# bge-small truncates input at 512 tokens, so chunks are sized to fit the window
# (an 800-token chunk would leave ~40% of its text invisible to the vector side).
CHUNK_TOKENS = int(os.getenv("RAG_CHUNK_TOKENS", "420"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "60"))
