"""Read-only API over saved evaluation results (`/evals`). No evaluation runs from here - use the CLI."""
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
