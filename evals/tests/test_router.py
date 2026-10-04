"""Router tests on a bare FastAPI app (no DB, no LLM)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from evals.router import router


@pytest.fixture
def client(tmp_path, monkeypatch):
    res = tmp_path / "results"
    res.mkdir()
    (res / "replay-a.json").write_text(json.dumps({"run_id": "replay-a", "mode": "replay", "created_at": "2026-10-01T00:00:00+00:00",
                                                  "summary": {"routing_accuracy": 1.0}, "cases": [{"id": "x"}]}))
    (res / "live-b.json").write_text(json.dumps({"run_id": "live-b", "mode": "live", "created_at": "2026-10-02T00:00:00+00:00",
                                                "summary": {}, "cases": []}))
    (res / "junk.json").write_text("{not json")
    (res / "backtest_latest.json").write_text(json.dumps({"buckets": [], "observations": [1, 2]}))
    monkeypatch.setenv("EVALS_RESULTS_DIR", str(res))
    monkeypatch.setenv("RAG_BENCHMARK_PATH", str(tmp_path / "rag.json"))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path


def test_list_runs_newest_first_without_cases(client):
    c, _ = client
    runs = c.get("/evals/runs").json()
    assert [r["run_id"] for r in runs] == ["live-b", "replay-a"]
    assert "cases" not in runs[0]


def test_get_run(client):
    c, _ = client
    assert c.get("/evals/runs/replay-a").json()["cases"] == [{"id": "x"}]
    assert c.get("/evals/runs/nope").status_code == 404
    assert c.get("/evals/runs/..%2Fsecret").status_code in (400, 404)


def test_backtest_latest(client):
    c, _ = client
    assert "observations" not in c.get("/evals/backtest/latest").json()
    assert c.get("/evals/backtest/latest?include_observations=true").json()["observations"] == [1, 2]


def test_rag_latest(client):
    c, tmp = client
    assert c.get("/evals/rag/latest").json()["available"] is False
    (tmp / "rag.json").write_text(json.dumps({"recall_at_5": 0.8}))
    assert c.get("/evals/rag/latest").json() == {"available": True, "data": {"recall_at_5": 0.8}}


def test_committed_results_are_served():
    """The results committed in the repo load through the real router paths."""
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    runs = c.get("/evals/runs").json()
    assert any(r["mode"] == "replay" for r in runs)
    bt = c.get("/evals/backtest/latest").json()
    assert {b["verdict"] for b in bt["buckets"]} == {"BUY", "HOLD", "SELL", "ALL"}
