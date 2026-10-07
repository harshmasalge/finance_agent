"""Agent runs survive the browser disconnecting; every API key is used.

Run: POSTGRES_URL=sqlite:// python -m pytest backend/agent/tests -q
"""
import asyncio
import json
import os

os.environ.setdefault("POSTGRES_URL", "sqlite://")
os.environ["APP_MODE"] = "demo"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agent import keypool
from backend.agent import runs as runs_mod
from backend.agent.keypool import KeyPool
from backend.db import models as core_models  # noqa: F401
from backend.db.database import Base
from backend.db.models import ChatMessage
from backend.routers import agent as agent_mod
from backend.services.auth import get_current_user_id


class FakeGraph:
    """Stands in for the LangGraph app: a few slow node updates, then a final answer."""
    def __init__(self, delay=0.15):
        self.delay = delay

    async def astream(self, state, **_):
        await asyncio.sleep(self.delay)
        yield {"orchestrator_node": {"intent": "direct_answer", "target_tickers": [], "evidence": [
            {"id": "R1", "agent": "Research Agent", "tool": "get_price", "input": {}, "output": {"last_close": float("nan")}}]}}
        await asyncio.sleep(self.delay)
        yield {"synthesis_node": {"final_answer": {"answer_type": "general", "headline": "All good", "sections": []}}}
        await asyncio.sleep(self.delay)
        yield {"validator_node": {"validation": {"status": "skipped", "issues": []}}}


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(agent_mod, "SessionLocal", Session)
    monkeypatch.setattr(agent_mod, "langgraph_app", FakeGraph())
    monkeypatch.setattr(agent_mod, "use_llm", lambda p, m: {"provider": "groq", "model": "x", "label": "Groq"})
    monkeypatch.setattr(agent_mod, "resolve", lambda p, m: {"provider": "groq", "model": "x", "label": "Groq"})
    app = FastAPI()
    app.include_router(agent_mod.agent_router)
    app.dependency_overrides[get_current_user_id] = lambda: 1
    with TestClient(app) as c:
        c.Session = Session
        yield c


def _events(resp, stop_after=None):
    out = []
    for line in resp.iter_lines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
            if stop_after and out[-1]["type"] == stop_after:
                break
    return out


def test_run_is_saved_listed_and_can_be_replayed(client):
    with client.stream("POST", "/agent/chat", json={"message": "hello"}) as r:
        events = _events(r)
    chat_id = events[0]["session_id"]
    assert events[-1]["type"] == "final" and events[-1]["payload"]["answer"]["headline"] == "All good"
    assert [e["seq"] for e in events] == list(range(len(events)))
    # NaN from a data source is stored as null (Postgres JSON and JSON.parse reject NaN).
    assert events[-1]["payload"]["evidence"][0]["output"]["last_close"] is None

    runs = client.get("/agent/runs").json()
    assert [(x["chat_id"], x["question"], x["status"]) for x in runs] == [(chat_id, "hello", "done")]

    db = client.Session()
    assert [m.role for m in db.query(ChatMessage).filter(ChatMessage.session_id == chat_id)] == ["user", "assistant"]

    # Re-attaching replays everything, or only the events after `after`.
    with client.stream("GET", f"/agent/runs/{chat_id}/events?after=0") as r:
        assert [e["seq"] for e in _events(r)] == [e["seq"] for e in events]
    with client.stream("GET", f"/agent/runs/{chat_id}/events?after={len(events) - 1}") as r:
        assert [e["type"] for e in _events(r)] == ["final"]

    # While a run is going, a second question in the same chat is refused.
    runs_mod._runs[chat_id] = runs_mod.Run(chat_id, 1, "busy", {})
    try:
        assert client.post("/agent/chat", json={"message": "again", "session_id": chat_id}).status_code == 409
    finally:
        runs_mod._runs.pop(chat_id, None)


def test_run_keeps_going_when_the_watcher_leaves():
    async def scenario():
        gate = asyncio.Event()

        async def work(run):
            run.emit({"type": "session"})
            await gate.wait()
            run.emit({"type": "step"})
            run.emit({"type": "final"})

        run = runs_mod.start_run(runs_mod.Run(4242, 1, "q", {}), work)
        watcher = run.follow()
        assert (await watcher.__anext__())["type"] == "session"
        await watcher.aclose()                  # the browser navigated away
        assert runs_mod.is_running(4242)
        gate.set()
        await run.task
        assert run.status == "done" and [e["type"] for e in run.events] == ["session", "step", "final"]
        assert [e["type"] async for e in run.follow(1)] == ["step", "final"]   # a later re-attach
        runs_mod._runs.pop(4242, None)

    asyncio.run(scenario())


def test_failed_run_reports_an_error():
    async def scenario():
        async def work(run):
            raise RuntimeError("boom")

        run = runs_mod.start_run(runs_mod.Run(4243, 1, "q", {}), work)
        events = [e async for e in run.follow()]
        assert run.status == "error" and "boom" in events[-1]["content"]
        runs_mod._runs.pop(4243, None)

    asyncio.run(scenario())


def test_unknown_run_is_404(client):
    assert client.get("/agent/runs/999/events").status_code == 404


def test_keys_rotate_and_failing_keys_rest(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(keypool.time, "monotonic", lambda: clock[0])
    pool = KeyPool("p", ["a", "b", "c"])
    assert [pool.pick() for _ in range(4)] == ["a", "b", "c", "a"]
    pool.rest("b", 429, "5")
    assert [pool.pick() for _ in range(3)] == ["c", "a", "c"]   # b is resting
    assert pool.pick(exclude={"a", "c"}) == "b"                   # every other key tried: a resting key is still offered
    clock[0] += 6
    assert "b" in [pool.pick() for _ in range(3)]                 # b is back after Retry-After
    pool.rest("a", 402)
    pool.rest("b", 401)
    pool.rest("c", 429)
    assert pool.pick() == "c"                                      # all resting: the soonest available


def test_all_key_variables_are_merged(monkeypatch):
    from backend.agent import utils
    monkeypatch.setenv("OPENROUTER_API_KEYS", "k1, k2")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k2,k3")
    assert utils._keys("openrouter") == ["k1", "k2", "k3"]
