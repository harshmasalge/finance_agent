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

    # Every dataset case is listed, so the run shows what is still to do (not only what was asked).
    order = list(by_id)
    cases = [by_id[cid] for cid in order]
    current = iter(order)

    def lookup(question, history):  # called once per case, in dataset order
        cid = next(current)
        if cid not in mapping:
            raise LookupError("not asked yet")
        if cid not in payloads:
            raise LookupError(f"chat #{mapping[cid]} has no answer yet")
        return payloads[cid]

    asked = [c for c in order if c in mapping]
    res = run_eval("live", cases, chat_fn=lookup, run_id=req.run_id,
                   fixtures_path="chats: " + ", ".join(f"{c}=#{mapping[c]}" for c in asked))
    for c in res["cases"]:  # plain reasons instead of "live call failed: ..."
        if c["status"] == "not_run" and (c.get("reason") or "").startswith("live call failed: "):
            c["reason"] = c["reason"][len("live call failed: "):]
            if c["id"] in mapping:
                c["chat_id"] = mapping[c["id"]]
        elif c["id"] in mapping:
            c["chat_id"] = mapping[c["id"]]
    res["chats"] = {c: mapping[c] for c in asked}
    save(res, _results_dir())
    return {k: res[k] for k in ("run_id", "summary", "chats")} | {
        "cases": [{"id": c["id"], "status": c["status"], "passed": c.get("passed"),
                   "failed": [k["name"] for k in c.get("checks", []) if k["gating"] and k["passed"] is False],
                   "reason": c.get("reason")} for c in res["cases"]]}


# --------------------------------------------------------------------------------------------
# Combined view: every scored case from every run, filterable by the model that answered.
# --------------------------------------------------------------------------------------------

UNRECORDED = "unrecorded"
_MODEL_NAMES = {"claude-haiku-5-5": "Claude Haiku 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-opus-5-5": "Claude Opus 5.5"}


def model_key(llm: Any) -> str:
    if not isinstance(llm, dict) or not llm.get("model"):
        return UNRECORDED
    return f"{llm.get('provider')}:{llm['model']}"


def model_label(llm: Any) -> str:
    if not isinstance(llm, dict) or not llm.get("model"):
        return "Model not recorded"
    m = llm["model"]
    name = _MODEL_NAMES.get(m) or m.split("/")[-1].replace(":free", " (free)")
    return f"{name} · {llm.get('label') or llm.get('provider')}"


@router.get("/overview")
def overview(model: str = "all") -> Dict[str, Any]:
    """All dataset cases with their latest result per model across every saved run; summary
    metrics recomputed for the selected model ('all' = the latest result of every model)."""
    from evals.run import METRIC_NOTES, load_dataset, summarize

    latest: Dict[tuple, Dict[str, Any]] = {}  # (case id, model key) -> newest evaluated result
    runs = []
    for p in _results_dir().glob("*.json"):
        if p.name.startswith("backtest"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "run_id" not in d or "cases" not in d:
            continue
        runs.append({"run_id": d["run_id"], "mode": d.get("mode"), "created_at": d.get("created_at"), "git_commit": d.get("git_commit")})
        chats = d.get("chats") or {}
        for c in d["cases"]:
            if c.get("status") != "evaluated":
                continue
            k = (c["id"], model_key(c.get("llm")))
            row = {**c, "run_id": d["run_id"], "mode": d.get("mode"), "created_at": d.get("created_at"),
                   "model_key": k[1], "model_label": model_label(c.get("llm")), "chat_id": c.get("chat_id") or chats.get(c["id"])}
            if k not in latest or (row["created_at"] or "") > (latest[k]["created_at"] or ""):
                latest[k] = row

    models: Dict[str, Dict[str, Any]] = {}
    for (_, mk), row in latest.items():
        e = models.setdefault(mk, {"key": mk, "label": row["model_label"], "n_evaluated": 0, "n_passed": 0})
        e["n_evaluated"] += 1
        e["n_passed"] += 1 if row.get("passed") else 0

    if model != "all" and model not in models:
        raise HTTPException(404, f"no results for model {model}")
    chosen = [r for (_, mk), r in latest.items() if model == "all" or mk == model]

    dataset_cases = load_dataset()
    order = {c["id"]: i for i, c in enumerate(dataset_cases)}
    scored_ids = {r["id"] for r in chosen}
    not_run = [{"id": c["id"], "question": c["question"], "history": c["history"], "status": "not_run", "passed": None,
                "reason": "not run yet" + ("" if model == "all" else " with this model"), "notes": c.get("notes"),
                "expected": {k: c[k] for k in ("expected_intent", "expected_tickers", "expected_answer_type")},
                "model_key": None, "model_label": None}
               for c in dataset_cases if c["id"] not in scored_ids]
    cases = sorted(chosen, key=lambda r: (order.get(r["id"], 999), r["model_label"])) + not_run
    summary = summarize(chosen)
    summary.update({"n_cases": len(dataset_cases), "n_not_run": len(not_run), "n_results": len(chosen)})
    return {
        "run_id": "all", "mode": "combined", "model": model,
        "created_at": max((r["created_at"] or "" for r in chosen), default=None), "git_commit": None,
        "dataset": {"path": "evals/dataset.yaml", "n_cases": len(dataset_cases)}, "fixtures": None, "judge": False,
        "models": sorted(models.values(), key=lambda m: (m["key"] == UNRECORDED, m["label"])),
        "runs": sorted(runs, key=lambda r: r.get("created_at") or "", reverse=True),
        "summary": summary, "metric_notes": METRIC_NOTES, "cases": cases,
    }
