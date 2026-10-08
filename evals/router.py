"""API over saved evaluation results (`/evals`), plus scoring of real advisor chats (`/evals/live/score`)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

router = APIRouter(prefix="/evals", tags=["Evaluation"])


def _results_dir() -> Path:
    return Path(os.getenv("EVALS_RESULTS_DIR", ROOT / "evals" / "results"))


def _rag_path() -> Path:
    return Path(os.getenv("RAG_BENCHMARK_PATH", ROOT / "data" / "benchmarks" / "rag_latest.json"))


def _read(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"could not read {p.name}: {e}") from e


@router.get("/runs")
def list_runs() -> List[Dict[str, Any]]:
    """All saved eval runs, newest first, with their summary metrics (no per-case detail)."""
    out = []
    for p in _results_dir().glob("*.json"):
        if p.name.startswith("backtest"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "run_id" in d and "summary" in d:
            out.append({k: d.get(k) for k in ("run_id", "mode", "created_at", "git_commit", "dataset", "fixtures", "judge", "summary")})
    return sorted(out, key=lambda r: r.get("created_at") or "", reverse=True)


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> Dict[str, Any]:
    """One eval run with per-case checks."""
    if not RUN_ID.match(run_id):
        raise HTTPException(400, "invalid run id")
    p = _results_dir() / f"{run_id}.json"
    if not p.is_file():
        raise HTTPException(404, f"run {run_id} not found")
    return _read(p)


@router.get("/backtest/latest")
def backtest_latest(include_observations: bool = False) -> Dict[str, Any]:
    """Latest scorecard backtest (python -m evals.backtest). Per-stock observations only on request."""
    p = _results_dir() / "backtest_latest.json"
    if not p.is_file():
        raise HTTPException(404, "no backtest yet - run `python -m evals.backtest`")
    d = _read(p)
    if not include_observations:
        d.pop("observations", None)
    return d


@router.get("/rag/latest")
def rag_latest() -> Dict[str, Any]:
    """RAG retrieval benchmark written by backend/rag/benchmark.py, if it has been run."""
    p = _rag_path()
    if not p.is_file():
        return {"available": False, "message": "RAG benchmark not run yet (python -m backend.rag.benchmark)."}
    return {"available": True, "data": _read(p)}


# --------------------------------------------------------------------------------------------
# Live evaluation of real chats: dataset questions are asked through the normal advisor
# (POST /agent/chat), so they become ordinary chats in the history; this endpoint then scores
# those saved answers with the same checks as `python -m evals.run`.
# --------------------------------------------------------------------------------------------

from pydantic import BaseModel  # noqa: E402
from fastapi import Depends  # noqa: E402


class ScoreChatsRequest(BaseModel):
    run_id: str
    cases: Dict[str, int]  # dataset case id -> chat id that asked it


@router.get("/dataset")
def dataset() -> List[Dict[str, Any]]:
    """The evaluation questions (with any earlier turns for follow-up cases)."""
    from evals.run import load_dataset
    return load_dataset()


def _require_demo():
    from backend.app_mode import require_demo_mode
    return require_demo_mode()


@router.post("/live/score", dependencies=[Depends(_require_demo)])
def score_chats(req: ScoreChatsRequest) -> Dict[str, Any]:
    """Score saved chats against their dataset cases and save the run (merged with the cases
    already scored under the same run id), so a live run can be built up a few cases at a time."""
    from backend.db.database import SessionLocal
    from backend.db.models import ChatMessage
    from evals.run import load_dataset, run as run_eval, save

    if not RUN_ID.match(req.run_id):
        raise HTTPException(400, "invalid run id")
    by_id = {c["id"]: c for c in load_dataset()}
    unknown = sorted(set(req.cases) - set(by_id))
    if unknown:
        raise HTTPException(400, f"unknown case ids: {unknown}")

    path = _results_dir() / f"{req.run_id}.json"
    mapping: Dict[str, int] = {}
    if path.is_file():
        mapping.update({k: int(v) for k, v in (_read(path).get("chats") or {}).items()})
    mapping.update(req.cases)

    db = SessionLocal()
    try:
        payloads = {}
        for case_id, chat_id in mapping.items():
            msg = (db.query(ChatMessage).filter(ChatMessage.session_id == chat_id, ChatMessage.role == "assistant")
                   .order_by(ChatMessage.id.desc()).first())
            if msg and msg.payload:
                payloads[case_id] = msg.payload
    finally:
        db.close()

    order = [cid for cid in by_id if cid in mapping]  # dataset order
    cases = [by_id[cid] for cid in order]
    current = iter(order)

    def lookup(question, history):  # called once per case, in order
        cid = next(current)
        if cid not in payloads:
            raise RuntimeError(f"chat {mapping[cid]} has no answer yet")
        return payloads[cid]

    res = run_eval("live", cases, chat_fn=lookup, run_id=req.run_id,
                   fixtures_path="chats: " + ", ".join(f"{c}=#{mapping[c]}" for c in order))
    res["chats"] = {c: mapping[c] for c in order}
    save(res, _results_dir())
    return {k: res[k] for k in ("run_id", "summary", "chats")} | {
        "cases": [{"id": c["id"], "status": c["status"], "passed": c.get("passed"),
                   "failed": [k["name"] for k in c.get("checks", []) if k["gating"] and k["passed"] is False],
                   "reason": c.get("reason")} for c in res["cases"]]}
