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
    got = {x["id"]: x for x in r.json()["cases"]}
    assert len(got) == 25 and got["direct-hi"]["status"] == "evaluated"
    assert got["research-lt"]["status"] == "not_run" and got["research-lt"]["reason"] == "not asked yet"

    # A second call adds a case to the same run; a chat without an answer is reported, not fatal.
    r = c.post("/evals/live/score", json={"run_id": "live-test", "cases": {"direct-pe": empty.id}})
    got = {x["id"]: x for x in r.json()["cases"]}
    assert got["direct-hi"]["status"] == "evaluated" and got["direct-pe"]["status"] == "not_run"
    assert got["direct-pe"]["reason"] == f"chat #{empty.id} has no answer yet"
    saved = json.loads((tmp_path / "live-test.json").read_text())
    assert saved["chats"] == {"direct-hi": chat.id, "direct-pe": empty.id}
    assert c.get("/evals/runs/live-test").status_code == 200
    assert len(c.get("/evals/dataset").json()) == 25
    assert c.post("/evals/live/score", json={"run_id": "x", "cases": {"nope": 1}}).status_code == 400


def test_overview_combines_runs_and_filters_by_model(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALS_RESULTS_DIR", str(tmp_path))
    from evals.run import evaluate_case, load_dataset, run as run_eval, save
    cases = {c["id"]: c for c in load_dataset()}

    def payload(model, headline="Hello! I can help with Indian stocks."):
        return {"answer": {"answer_type": "general", "headline": headline, "verdict": None, "sections": [], "data_gaps": []},
                "evidence": [], "intent": "direct_answer", "tickers": [], "validation": {"status": "skipped", "issues": []},
                "duration_s": 2.0, "llm": model and {"provider": model[0], "model": model[1], "label": model[0].title()}}

    answers = {"direct-hi": payload(("anthropic", "claude-haiku-5-5"))}
    save(run_eval("live", [cases["direct-hi"]], chat_fn=lambda q, h: answers["direct-hi"], run_id="a"), tmp_path)
    save(run_eval("live", [cases["direct-hi"]], chat_fn=lambda q, h: payload(("groq", "openai/gpt-oss-120b")), run_id="b"), tmp_path)
    save(run_eval("replay", [cases["direct-hi"]], fixtures={"hi": payload(None)}, run_id="c"), tmp_path)

    app = FastAPI(); app.include_router(evals_router.router)
    c = TestClient(app)
    allv = c.get("/evals/overview").json()
    keys = {m["key"]: m for m in allv["models"]}
    assert set(keys) == {"anthropic:claude-haiku-5-5", "groq:openai/gpt-oss-120b", "unrecorded"}
    assert keys["anthropic:claude-haiku-5-5"]["label"] == "Claude Haiku 5.5 · Anthropic"
    scored = [x for x in allv["cases"] if x["status"] == "evaluated"]
    assert len(scored) == 3 and allv["summary"]["n_results"] == 3 and allv["summary"]["n_not_run"] == 24
    one = c.get("/evals/overview", params={"model": "anthropic:claude-haiku-5-5"}).json()
    assert [x["model_key"] for x in one["cases"] if x["status"] == "evaluated"] == ["anthropic:claude-haiku-5-5"]
    assert one["summary"]["grounding_control_numbers"] == 0 and one["summary"]["case_pass_rate"] is not None
    assert c.get("/evals/overview", params={"model": "nope"}).status_code == 404
    assert evaluate_case(cases["direct-hi"], answers["direct-hi"])["llm"]["model"] == "claude-haiku-5-5"
