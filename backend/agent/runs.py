"""
Agent runs that outlive the browser connection.

A question starts a background task that runs the agent graph and records every progress
event. The HTTP stream only *watches* the run: if the user navigates away, reloads the page
or loses the connection, the run keeps going (the answer is saved to the chat when it
finishes) and the UI can re-attach and replay the events so far.

Runs live in this process's memory (the API runs as a single worker); finished runs are
forgotten after a few minutes because their answer is in the database by then.
"""
import asyncio
import math
import time
from typing import AsyncIterator, Callable, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

KEEP_FINISHED_S = 10 * 60


def json_safe(value):
    """Replace NaN/Infinity (e.g. a missing yfinance close) with None. Postgres JSON columns and
    the browser's JSON.parse both reject them, which used to lose a finished answer."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "item") and callable(value.item) and type(value).__module__ == "numpy":
        return json_safe(value.item())  # numpy scalars
    return value


class Run:
    def __init__(self, chat_id: int, user_id: int, question: str, llm: dict):
        self.chat_id = chat_id
        self.user_id = user_id
        self.question = question
        self.llm = llm
        self.events: List[dict] = []
        self.status = "running"          # running | done | error
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.task: Optional[asyncio.Task] = None
        self._changed = asyncio.Event()

    def emit(self, event: dict) -> None:
        self.events.append({**json_safe(event), "seq": len(self.events)})
        if event.get("type") == "final":
            self.status = "done"
        elif event.get("type") == "error":
            self.status = "error"
        self._wake()

    def _wake(self) -> None:
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    def finish(self) -> None:
        if self.status == "running":  # ended without a final/error event (e.g. cancelled)
            self.emit({"type": "error", "content": "The run stopped unexpectedly."})
        self.finished_at = time.time()
        self._wake()

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    def summary(self) -> dict:
        return {"chat_id": self.chat_id, "question": self.question, "llm": self.llm, "status": self.status,
                "started_at": self.started_at, "events": len(self.events)}

    async def follow(self, after: int = 0) -> AsyncIterator[dict]:
        """Replay events from index `after`, then stream new ones until the run ends."""
        i = max(0, after)
        while True:
            waiter = self._changed
            while i < len(self.events):
                yield self.events[i]
                i += 1
            if self.finished:
                return
            await waiter.wait()


_runs: Dict[int, Run] = {}


def _prune() -> None:
    now = time.time()
    for cid in [c for c, r in _runs.items() if r.finished and now - (r.finished_at or now) > KEEP_FINISHED_S]:
        _runs.pop(cid, None)


def get_run(chat_id: int, user_id: int) -> Optional[Run]:
    _prune()
    run = _runs.get(chat_id)
    return run if run and run.user_id == user_id else None


def is_running(chat_id: int) -> bool:
    run = _runs.get(chat_id)
    return bool(run and not run.finished)


def user_runs(user_id: int) -> List[Run]:
    _prune()
    return [r for r in _runs.values() if r.user_id == user_id]


def start_run(run: Run, work: Callable[[Run], "asyncio.Future"]) -> Run:
    """Start `work(run)` in the background; it reports progress with run.emit()."""
    _prune()

    async def runner():
        try:
            await work(run)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # work() normally reports its own errors
            logger.error("Agent run failed", chat_id=run.chat_id, error=str(e))
            run.emit({"type": "error", "content": f"Something went wrong: {e}"})
        finally:
            run.finish()

    _runs[run.chat_id] = run
    run.task = asyncio.create_task(runner())
    return run
