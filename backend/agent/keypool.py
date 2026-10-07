"""
Use every API key configured for a provider.

Each request picks the next key in turn (round robin). If the provider answers with a
key-specific error - 429 rate limit, 402 out of credit, 401/403 bad or blocked key - the
same request is sent again straight away with the next key, and the failing key is
rested for a while (429: the provider's Retry-After or 20 s; 401/402/403: 30 min).
Only when every key has failed does the error reach the SDK, which then backs off and
retries as usual.

This works at the HTTP-client level (the SDKs call `client.send()` for every request),
so it covers plain calls, tool calling, structured output and streaming, for both the
OpenAI-compatible providers and Anthropic.
"""
import threading
import time
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

ROTATE_STATUSES = {401, 402, 403, 429}
RATE_LIMIT_REST_S = 20.0
BAD_KEY_REST_S = 30 * 60.0


def mask(key: str) -> str:
    return f"…{key[-4:]}" if len(key) > 8 else "…"


class KeyPool:
    """Thread-safe round robin over a provider's keys, skipping keys that are resting."""

    def __init__(self, name: str, keys: List[str]):
        self.name = name
        self.keys = list(keys)
        self._next = 0
        self._rest_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def pick(self, exclude: Optional[set] = None) -> str:
        exclude = exclude or set()
        now = time.monotonic()
        with self._lock:
            n = len(self.keys)
            candidates = [self.keys[(self._next + i) % n] for i in range(n)]
            candidates = [k for k in candidates if k not in exclude] or candidates
            ready = [k for k in candidates if self._rest_until.get(k, 0) <= now]
            # All resting: use the one that becomes available first.
            key = ready[0] if ready else min(candidates, key=lambda k: self._rest_until.get(k, 0))
            self._next = (self.keys.index(key) + 1) % n
            return key

    def rest(self, key: str, status: int, retry_after: Optional[str] = None) -> None:
        seconds = BAD_KEY_REST_S if status in (401, 402, 403) else RATE_LIMIT_REST_S
        if status == 429 and retry_after:
            try:
                seconds = min(max(float(retry_after), 1.0), 300.0)
            except ValueError:
                pass
        with self._lock:
            self._rest_until[key] = time.monotonic() + seconds
        logger.warning("API key rested", provider=self.name, key=mask(key), status=status, seconds=round(seconds))

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            resting = sum(1 for k in self.keys if self._rest_until.get(k, 0) > now)
        return {"keys": len(self.keys), "resting": resting}


def _apply(request, key: str, header: str) -> None:
    request.headers[header] = f"Bearer {key}" if header.lower() == "authorization" else key


def make_clients(sdk, pool: KeyPool, header: str):
    """(sync_client, async_client) for an SDK module (`openai` or `anthropic`) that send
    every request with the pool's next key and fail over to the other keys."""

    class RotatingClient(sdk.DefaultHttpxClient):
        def send(self, request, **kwargs):
            tried: set = set()
            while True:
                key = pool.pick(tried)
                tried.add(key)
                _apply(request, key, header)
                response = super().send(request, **kwargs)
                if response.status_code not in ROTATE_STATUSES:
                    return response
                pool.rest(key, response.status_code, response.headers.get("retry-after"))
                if len(tried) >= len(pool.keys):
                    return response  # every key failed: let the SDK handle the error
                response.close()

    class AsyncRotatingClient(sdk.DefaultAsyncHttpxClient):
        async def send(self, request, **kwargs):
            tried: set = set()
            while True:
                key = pool.pick(tried)
                tried.add(key)
                _apply(request, key, header)
                response = await super().send(request, **kwargs)
                if response.status_code not in ROTATE_STATUSES:
                    return response
                pool.rest(key, response.status_code, response.headers.get("retry-after"))
                if len(tried) >= len(pool.keys):
                    return response
                await response.aclose()

    return RotatingClient(), AsyncRotatingClient()
