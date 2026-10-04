"""Embedding model + Chroma vector store.

Chroma: HTTP client to `CHROMA_URL` (the docker-compose service) when reachable, otherwise an
embedded `PersistentClient` under `data/chroma`. Force one with RAG_CHROMA_MODE=http|embedded.
Embeddings are computed locally with sentence-transformers (no API calls) and passed to Chroma
explicitly, so both client modes store identical vectors."""
from __future__ import annotations

import os
import socket
import threading
from typing import Any, List, Optional
from urllib.parse import urlsplit

from backend.rag import config

_lock = threading.Lock()
_embedder: Any = None
_embedder_name: Optional[str] = None
_collection: Any = None
_client_mode: Optional[str] = None


def get_embedder():
    """Lazily load the sentence-transformers model (bge-small, falling back to MiniLM)."""
    global _embedder, _embedder_name
    with _lock:
        if _embedder is None:
            from sentence_transformers import SentenceTransformer
            try:
                _embedder = SentenceTransformer(config.EMBED_MODEL, device="cpu")
                _embedder_name = config.EMBED_MODEL
            except Exception:
                _embedder = SentenceTransformer(config.EMBED_FALLBACK, device="cpu")
                _embedder_name = config.EMBED_FALLBACK
        return _embedder


def embedder_name() -> Optional[str]:
    """Name of the loaded embedding model (None until first use)."""
    return _embedder_name


def embed_passages(texts: List[str], batch_size: int = 32) -> List[List[float]]:
    """Normalised passage embeddings."""
    vecs = get_embedder().encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()


def embed_query(text: str) -> List[float]:
    """Normalised query embedding (bge query instruction prefix applied)."""
    prefix = config.QUERY_PREFIX if "bge" in (config.EMBED_MODEL or "").lower() else ""
    return get_embedder().encode([prefix + text], normalize_embeddings=True, show_progress_bar=False)[0].tolist()


def _http_reachable(url: str, timeout: float = 0.5) -> bool:
    parts = urlsplit(url)
    try:
        with socket.create_connection((parts.hostname or "localhost", parts.port or 8000), timeout=timeout):
            return True
    except OSError:
        return False


def get_collection(reset: bool = False):
    """The Chroma collection holding chunk vectors (cosine space)."""
    global _collection, _client_mode
    with _lock:
        if _collection is not None and not reset:
            return _collection
        import chromadb
        from chromadb.config import Settings
        mode = os.getenv("RAG_CHROMA_MODE", "auto")
        client = None
        if mode in ("auto", "http") and _http_reachable(config.CHROMA_URL):
            try:
                p = urlsplit(config.CHROMA_URL)
                client = chromadb.HttpClient(host=p.hostname, port=p.port or 8000, ssl=p.scheme == "https",
                                             settings=Settings(anonymized_telemetry=False))
                client.heartbeat()
                _client_mode = "http"
            except Exception:
                if mode == "http":
                    raise
                client = None
        if client is None:
            if mode == "http":
                raise RuntimeError(f"Chroma not reachable at {config.CHROMA_URL}")
            config.CHROMA_PATH.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(config.CHROMA_PATH), settings=Settings(anonymized_telemetry=False))
            _client_mode = "embedded"
        _collection = client.get_or_create_collection(config.COLLECTION, metadata={"hnsw:space": "cosine"})
        return _collection


def client_mode() -> Optional[str]:
    """'http' or 'embedded' once the collection has been opened."""
    return _client_mode


def reset_cache() -> None:
    """Forget the cached collection (tests / after changing config paths)."""
    global _collection, _client_mode
    with _lock:
        _collection = None
        _client_mode = None
