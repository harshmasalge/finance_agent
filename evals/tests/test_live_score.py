"""Scoring real advisor chats via POST /evals/live/score (no LLM)."""
import json
import os

os.environ.setdefault("POSTGRES_URL", "sqlite://")
os.environ["APP_MODE"] = "demo"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.db.database as database
from backend.db import models as core_models  # noqa: F401
from backend.db.models import ChatMessage, ChatSession
from evals import router as evals_router


def test_score_chats_merges_cases_into_one_run(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", Session)
    monkeypatch.setenv("EVALS_RESULTS_DIR", str(tmp_path))
    db = Session()
    payload = {"answer": {"answer_type": "general", "headline": "Hello! I can help with Indian stocks.", "verdict": None,
                          "sections": [], "data_gaps": []}, "evidence": [], "intent": "direct_answer", "tickers": [],
               "validation": {"status": "skipped", "issues": []}, "duration_s": 3.2}
    chat = ChatSession(user_id=1, title="hi")
    db.add(chat); db.commit()
    db.add_all([ChatMessage(session_id=chat.id, role="user", content="hi"),
                ChatMessage(session_id=chat.id, role="assistant", content="Hello", payload=payload)])
    empty = ChatSession(user_id=1, title="pending")
    db.add(empty); db.commit()

    app = FastAPI(); app.include_router(evals_router.router)
    c = TestClient(app)
    r = c.post("/evals/live/score", json={"run_id": "live-test", "cases": {"direct-hi": chat.id}})
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()["cases"]] == ["direct-hi"] and r.json()["cases"][0]["status"] == "evaluated"

    # A second call adds a case to the same run; a chat without an answer is reported, not fatal.
    r = c.post("/evals/live/score", json={"run_id": "live-test", "cases": {"direct-pe": empty.id}})
    got = {x["id"]: x for x in r.json()["cases"]}
    assert set(got) == {"direct-hi", "direct-pe"} and got["direct-pe"]["status"] == "not_run"
    saved = json.loads((tmp_path / "live-test.json").read_text())
    assert saved["chats"] == {"direct-hi": chat.id, "direct-pe": empty.id}
    assert c.get("/evals/runs/live-test").status_code == 200
    assert len(c.get("/evals/dataset").json()) == 25
    assert c.post("/evals/live/score", json={"run_id": "x", "cases": {"nope": 1}}).status_code == 400
