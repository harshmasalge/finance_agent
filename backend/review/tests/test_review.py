"""Review workflow tests: SQLite + fake LLM, no network, no API keys.

Run: POSTGRES_URL=sqlite:// python -m pytest backend/review/tests -q
"""
import copy
import json
import os
from pathlib import Path

os.environ.setdefault("POSTGRES_URL", "sqlite://")

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import models as core_models  # noqa: F401  (registers core tables)
from backend.db.database import Base, get_db
from backend.db.models import ChatMessage, ChatSession
from backend.review import models as review_models  # noqa: F401
from backend.review.connector import NotPublishable, ResearchNotesConnector
from backend.review.correction import CorrectionAgent, CorrectionResult
from backend.review.models import AnswerStatus, ResearchNote
from backend.review.notes import analyst_notes_for
from backend.review.router import get_connector, get_correction_agent, router
from backend.services.auth import get_or_create_default_user

FIXTURES = json.loads((Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "answers.json").read_text(encoding="utf-8"))
PB = next(f for f in FIXTURES if f["payload"].get("scorecards"))  # POLICYBZR.NS stock analysis, score -11.6 HOLD


class FakeLLM:
    """Stands in for get_structured_llm(CorrectionResult): returns a scripted result and records calls."""

    def __init__(self, make=None):
        self.make, self.calls = make, []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.make is None:
            raise RuntimeError("LLM should not have been called")
        return self.make(messages)


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    llm = FakeLLM()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_correction_agent] = lambda: CorrectionAgent(llm=llm)
    client = TestClient(app)

    def add_answer(payload=None, question=None) -> int:
        db = Session()
        user = get_or_create_default_user(db)
        chat = ChatSession(user_id=user.id, title="t")
        db.add(chat)
        db.commit()
        db.add(ChatMessage(session_id=chat.id, role="user", content=question or PB["question"]))
        msg = ChatMessage(session_id=chat.id, role="assistant", content="x", payload=copy.deepcopy(payload or PB["payload"]))
        db.add(msg)
        db.commit()
        mid = msg.id
        db.close()
        return mid

    yield {"client": client, "Session": Session, "llm": llm, "add": add_answer, "app": app}
    engine.dispose()


def test_lazy_v1_creation(env):
    c, mid = env["client"], env["add"]()
    db = env["Session"]()
    assert db.get(AnswerStatus, mid) is None  # nothing until first review access
    r = c.get(f"/review/{mid}").json()
    assert r["status"] == "draft" and r["current_version"] == 1
    assert [v["version"] for v in r["versions"]] == [1] and r["versions"][0]["author"] == "agent"
    assert r["versions"][0]["answer"] == PB["payload"]["answer"]
    assert len(c.get(f"/review/{mid}").json()["versions"]) == 1  # idempotent
    assert c.get("/review/999999").status_code == 404


def test_accepted_llm_correction_creates_version_and_change_log(env):
    c, mid = env["client"], env["add"]()
    new_headline = "PB Fintech is at a 52-week low after a 50% fall; signals are mixed, so HOLD."

    def make(messages):
        assert "52-week low" in messages[-1].content  # the correction reached the prompt
        a = copy.deepcopy(PB["payload"]["answer"])
        a["headline"] = new_headline
        a["verdict"] = "BUY"  # the LLM must not be able to change the verdict
        a["sections"][1]["claims"][1]["citations"] = ["S2", "Z9"]  # invalid id is dropped
        return CorrectionResult(category="judgement", accepted=True, revised_answer=a,
                                change_log=[{"path": "headline", "before": "x", "after": new_headline, "reason": "Lead with the drawdown (S2)."}])

    env["llm"].make = make
    r = c.post(f"/review/{mid}/correct", json={"text": "The headline should lead with the 52-week low."}).json()
    assert r["accepted"] is True and r["new_version"] == 2 and r["source"] == "llm"
    assert {e["path"] for e in r["change_log"]} == {"headline"}
    assert r["change_log"][0]["reason"] == "Lead with the drawdown (S2)."
    st = r["review"]
    assert st["current_version"] == 2 and st["status"] == "draft"
    v2 = st["versions"][1]
    assert v2["author"] == "analyst" and v2["feedback_id"] == r["feedback"]["id"]
    assert v2["answer"]["headline"] == new_headline and v2["answer"]["verdict"] == "HOLD"
    assert v2["answer"]["sections"][1]["claims"][1]["citations"] == ["S2"]
    db = env["Session"]()
    assert db.get(ChatMessage, mid).payload["answer"]["headline"] == new_headline  # chat shows current version
    assert db.get(ChatMessage, mid).payload["review"]["version"] == 2


def test_rejected_correction_pushback_cites_evidence(env):
    c, mid = env["client"], env["add"]()
    r = c.post(f"/review/{mid}/correct", json={"text": "RSI should be 45, not 18"}).json()
    assert r["accepted"] is False and r["category"] == "fact" and r["new_version"] is None
    assert "R1" in r["pushback"] and "18.2" in r["pushback"]
    assert env["llm"].calls == []  # decided from evidence alone
    assert r["review"]["current_version"] == 1 and r["feedback"]["accepted"] is False

    env["llm"].make = lambda m: CorrectionResult(category="fact", accepted=False, pushback="R2 reports revenue growth 40.1%, not 4%.",
                                                 revised_answer=PB["payload"]["answer"])
    r = c.post(f"/review/{mid}/correct", json={"text": "Revenue growth was weak"}).json()
    assert r["accepted"] is False and "R2" in r["pushback"] and r["review"]["current_version"] == 1


def test_weighting_override_flips_verdict_deterministically(env):
    c = env["client"]
    results = []
    for _ in range(2):
        mid = env["add"]()
        r = c.post(f"/review/{mid}/correct", json={"text": "Ignore the valuation factor - the PEG uses one-off earnings."}).json()
        results.append(r)
    assert env["llm"].calls == []
    for r in results:
        assert r["category"] == "weighting" and r["accepted"] and r["new_version"] == 2
        v2 = r["review"]["versions"][1]
        card = v2["scorecards"][0]
        assert card["score"] == -27.6 and card["verdict"] == "SELL"
        assert v2["answer"]["verdict"] == "SELL"
        val = next(f for f in card["factors"] if f["name"] == "valuation")
        assert val["weight"] == 0 and val["base_weight"] == 1.0
        assert v2["answer"]["sections"][0]["title"] == "Analyst adjustments"
        assert "HOLD → SELL" in r["agent_response"]
        c1 = next(e for e in r["review"]["payload"]["evidence"] if e["id"] == "C1")
        assert c1["output"]["verdict"] == "SELL"
    strip = lambda r: [{k: v for k, v in e.items()} for e in r["change_log"]]
    assert strip(results[0]) == strip(results[1])  # same input, same output

    # "weight valuation higher" on top: doubles the current weight (0 stays 0) -> no-op, so test from v1 instead
    mid = env["add"]()
    r = c.post(f"/review/{mid}/correct", json={"text": "weight valuation higher"}).json()
    card = r["review"]["versions"][1]["scorecards"][0]
    assert card["score"] == 0.8 and card["verdict"] == "HOLD"


def test_approve_publishes_once_and_is_idempotent(env):
    c, mid = env["client"], env["add"]()
    c.post(f"/review/{mid}/correct", json={"text": "ignore valuation"})
    r = c.post(f"/review/{mid}/approve", json={}).json()
    assert r["publish"]["status"] == "published" and r["publish"]["idempotent"] is False
    assert r["review"]["status"] == "approved" and r["review"]["approved_version"] == 2
    note_id = r["note"]["id"]
    r2 = c.post(f"/review/{mid}/approve", json={"version": 2}).json()
    assert r2["note"]["id"] == note_id and r2["publish"]["idempotent"] is True
    notes = c.get("/research-notes").json()
    assert [n["id"] for n in notes] == [note_id]
    d = c.get(f"/research-notes/{note_id}").json()
    assert d["connector_status"] == "published" and d["verdict"] == "SELL" and d["body"]["version"] == 2
    assert "# POLICYBZR: SELL" in d["markdown"] and "ignore valuation" in d["markdown"]
    # the platform endpoint itself is idempotent
    again = c.post("/research-notes", json=d["body"]).json()
    assert again["id"] == note_id and again["duplicate"] is True


def test_external_connector_sends_once_with_idempotency_key(env):
    mid = env["add"]()
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(201, json={"id": "ext-1", "status": "created"})

    db = env["Session"]()
    env["app"].dependency_overrides[get_connector] = lambda: ResearchNotesConnector(
        db, url="https://notes.example.com/api/notes", transport=httpx.MockTransport(handler))
    c = env["client"]
    assert c.post(f"/review/{mid}/approve", json={}).json()["publish"]["id"] == "ext-1"
    assert c.post(f"/review/{mid}/approve", json={}).json()["publish"]["idempotent"] is True
    assert len(seen) == 1
    assert seen[0].headers["Idempotency-Key"] == f"finsight-note-{mid}-v1"
    assert json.loads(seen[0].content)["schema"] == "finsight.research_note/v1"


def test_draft_and_rejected_cannot_be_published(env):
    c, mid = env["client"], env["add"]()
    c.post(f"/review/{mid}/approve", json={})
    db = env["Session"]()
    note = db.query(ResearchNote).filter_by(message_id=mid).one()
    conn = ResearchNotesConnector(db)
    # correcting an approved answer puts it back to draft
    r = c.post(f"/review/{mid}/correct", json={"text": "ignore the xgboost signal"}).json()
    assert r["review"]["status"] == "draft"
    db.expire_all()
    note.connector_status = "pending"
    with pytest.raises(NotPublishable):
        conn.publish(note)
    assert c.post(f"/review/{mid}/reject", json={"reason": "Wrong peer group"}).json()["status"] == "rejected"
    db.expire_all()
    with pytest.raises(NotPublishable):
        conn.publish(note)
    # approving a version that does not exist
    assert c.post(f"/review/{mid}/approve", json={"version": 9}).status_code == 404


def test_feedback_jsonl_export_and_learning_loop(env):
    c, mid = env["client"], env["add"]()
    c.post(f"/review/{mid}/correct", json={"text": "ignore valuation"})
    c.post(f"/review/{mid}/correct", json={"text": "RSI should be 45"})
    res = c.get("/review/feedback/export.jsonl")
    assert res.status_code == 200 and res.headers["content-type"].startswith("application/x-ndjson")
    rows = [json.loads(l) for l in res.text.splitlines() if l.strip()]
    assert [r["label"] for r in rows] == ["accepted_correction", "rejected_correction"]
    assert rows[0]["question"] == PB["question"] and rows[0]["before"]["verdict"] == "HOLD" and rows[0]["after"]["verdict"] == "SELL"
    assert rows[1]["after"] is None and rows[0]["change_log"]

    db = env["Session"]()
    notes = analyst_notes_for(["POLICYBZR.NS"], db=db)
    assert len(notes) == 1 and notes[0]["id"] == "A1" and notes[0]["output"]["ticker"] == "POLICYBZR.NS"
    assert notes[0]["output"]["note"] == "ignore valuation"
    assert analyst_notes_for(["TCS.NS"], db=db) == []


def test_llm_unavailable_returns_503(env):
    c, mid = env["client"], env["add"]()
    r = c.post(f"/review/{mid}/correct", json={"text": "Detection Index should be 7, not 4"})
    assert r.status_code == 503 and "Weighting corrections" in r.json()["detail"]
    assert c.get(f"/review/{mid}").json()["feedback"] == []  # nothing logged on failure
