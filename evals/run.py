"""
Run the FinSight evaluation suite.

    # offline: score the recorded real answers (no LLM calls)
    python -m evals.run --mode replay --fixtures backend/tests/fixtures/answers.json

    # online: ask every dataset question through /agent/chat in-process (needs LLM credit)
    python -m evals.run --mode live [--cases research-lt,compare-tcs-infy] [--judge]

Writes evals/results/<run_id>.json (full per-case detail) and evals/results/<run_id>.md (summary table).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import yaml

from evals import metrics as M

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "dataset.yaml"
RESULTS_DIR = Path(os.getenv("EVALS_RESULTS_DIR", ROOT / "evals" / "results"))
GROUNDING_PASS = 0.9  # an answer passes grounding when >= 90% of its checkable numbers are found in cited evidence

ChatFn = Callable[[str, List[str]], dict]  # (question, earlier user turns) -> AnswerPayload


# --------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------


def load_dataset(path: Path | str = DATASET) -> List[dict]:
    """Load and minimally validate dataset.yaml."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cases = data["cases"]
    required = {"id", "question", "expected_intent", "expected_tickers", "expected_answer_type"}
    for c in cases:
        missing = required - set(c)
        if missing:
            raise ValueError(f"case {c.get('id')} is missing {sorted(missing)}")
        c.setdefault("must_include", [])
        c.setdefault("must_not_include", [])
        c.setdefault("history", [])
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("duplicate case ids")
    return cases


def _norm_q(q: str) -> str:
    return re.sub(r"[^a-z0-9&]+", " ", (q or "").lower()).strip()


def load_fixtures(path: Path | str) -> Dict[str, dict]:
    """Recorded answers: normalised question -> AnswerPayload."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return {_norm_q(r["question"]): r["payload"] for r in rows}


# --------------------------------------------------------------------------------------------
# Scoring one case
# --------------------------------------------------------------------------------------------


def _check(name: str, passed: Optional[bool], detail: str = "", value: Any = None, gating: bool = True) -> dict:
    return {"name": name, "passed": passed, "detail": detail, "value": value, "gating": gating}


def evaluate_case(case: dict, payload: dict, judge_llm: Optional[Callable] = None) -> dict:
    """Score one AnswerPayload against one dataset case. Pure apart from the optional judge call."""
    from backend.agent.synthesis import _deterministic_checks  # the app's own rule-based checker

    answer = payload.get("answer") or {}
    evidence = payload.get("evidence") or []
    intent = payload.get("intent")
    tickers = payload.get("tickers") or []
    text = M.answer_text(answer)
    checks: List[dict] = []

    routed = M.routing_correct(case["expected_intent"], intent)
    checks.append(_check("routing", routed, f"expected {case['expected_intent']}, got {intent}", intent))
    prf = M.ticker_prf(case["expected_tickers"], tickers)
    checks.append(_check("tickers", prf["f1"] == 1.0, f"expected {case['expected_tickers']}, got {tickers}", prf["f1"]))
    at = answer.get("answer_type")
    checks.append(_check("answer_type", at == case["expected_answer_type"], f"expected {case['expected_answer_type']}, got {at}", at))
    ok, err = M.schema_valid(answer)
    checks.append(_check("schema", ok, err or "FinalAnswer parses"))

    n_claims = sum(1 for _ in M.iter_claims(answer))
    cov = M.citation_coverage(answer)
    checks.append(_check("citation_coverage", None if cov is None else cov == 1.0,
                         "no claims" if cov is None else f"{cov:.0%} of {n_claims} claims cite evidence", cov))
    val = M.citation_validity(answer, evidence)
    bad = M.invalid_citations(answer, evidence)
    checks.append(_check("citation_validity", None if val is None else val == 1.0,
                         "nothing cited" if val is None else (f"unknown ids {bad}" if bad else "all cited ids exist"), val))
    g = M.number_grounding(answer, evidence)
    checks.append(_check("number_grounding", None if g["rate"] is None else g["rate"] >= GROUNDING_PASS,
                         "no checkable numbers" if g["rate"] is None else f"{g['grounded']}/{g['numbers']} numbers found in cited evidence",
                         g["rate"]))
    forb = M.forbidden_content(text, case["must_not_include"])
    checks.append(_check("forbidden_content", not forb, f"found {forb}" if forb else "none", forb))
    miss = M.missing_required(text, case["must_include"])
    checks.append(_check("must_include", None if not case["must_include"] else not miss,
                         f"missing {miss}" if miss else ("n/a" if not case["must_include"] else "all present"), miss))

    det = M.verdict_determinism(evidence, tickers, payload.get("scorecards"), answer)
    checks.append(_check("verdict_consistency", det["answer_consistent"],
                         "no verdict / nothing to score" if det["answer_consistent"] is None else
                         f"answer {answer.get('verdict')} vs scorecard " + ", ".join(f"{c['ticker']} {c['verdict']} ({c['score']:+})" for c in det["recomputed"])
                         + ("" if det["matches_stored"] is not None else " · answer recorded without a scorecard (pre-scorecard pipeline)"),
                         det["answer_consistent"]))

    if at == "general":
        checks.append(_check("rule_checker", None, "skipped for general answers (same as the app's validator)"))
    else:
        issues = _deterministic_checks(answer, {e.get("id") for e in evidence}, tickers)
        checks.append(_check("rule_checker", not issues, "; ".join(issues) if issues else "no issues", len(issues)))

    v = payload.get("validation") or {}
    vstatus = v.get("status")
    checks.append(_check("llm_validator", None if vstatus in (None, "skipped") else vstatus == "passed",
                         f"recorded status {vstatus}" + (f": {len(v.get('issues') or [])} issue(s)" if v.get("issues") else ""),
                         vstatus, gating=False))

    judge = None
    if judge_llm is not None and n_claims:
        from evals.judge import judge_answer
        judge = judge_answer(answer, evidence, judge_llm)
        checks.append(_check("judge_faithfulness", None if judge["faithfulness"] is None else judge["faithfulness"] >= 0.9,
                             f"{judge['counts']}", judge["faithfulness"], gating=False))

    gating = [c for c in checks if c["gating"] and c["passed"] is not None]
    return {
        "id": case["id"], "question": case["question"], "history": case["history"], "status": "evaluated",
        "passed": all(c["passed"] for c in gating),
        "expected": {k: case[k] for k in ("expected_intent", "expected_tickers", "expected_answer_type")},
        "actual": {"intent": intent, "tickers": tickers, "answer_type": at, "verdict": answer.get("verdict"),
                   "verdict_ticker": answer.get("verdict_ticker"), "headline": answer.get("headline")},
        "checks": checks,
        "metrics": {
            "routing": routed, "ticker_f1": prf["f1"], "answer_type_ok": at == case["expected_answer_type"], "schema_valid": ok,
            "claims": n_claims, "citation_coverage": cov, "citation_validity": val,
            "numbers": g["numbers"], "numbers_grounded": g["grounded"], "grounding_rate": g["rate"],
            "claims_with_numbers": g["claims_with_numbers"], "claims_fully_grounded": g["claims_fully_grounded"],
            "forbidden_hits": len(forb), "must_include_ok": None if not case["must_include"] else not miss,
            "verdict_deterministic": det["deterministic"], "verdict_matches_stored": det["matches_stored"],
            "verdict_consistent": det["answer_consistent"],
            "rule_checker_ok": next(c["passed"] for c in checks if c["name"] == "rule_checker"),
            "validator_status": vstatus, "validator_attempts": v.get("attempts"),
            "latency_s": payload.get("duration_s"), "evidence_items": len(evidence),
            **M.usage_from_payload(payload),
        },
        "ungrounded": g["ungrounded"],
        "scorecard_recheck": det,
        "judge": judge,
        "notes": case.get("notes"),
    }


# --------------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------------


def summarize(case_results: Sequence[dict], payloads: Sequence[dict] = ()) -> dict:
    """Aggregate per-case metrics. Every rate is over the cases where it applies; `n_*` give denominators."""
    ev = [c for c in case_results if c["status"] == "evaluated"]
    m = [c["metrics"] for c in ev]
    col = lambda k: [x[k] for x in m]  # noqa: E731
    nn = lambda k: sum(1 for x in m if x[k] is not None)  # noqa: E731
    nums = sum(x["numbers"] for x in m)
    grounded = sum(x["numbers_grounded"] for x in m)
    cwn = sum(x["claims_with_numbers"] for x in m)
    claims = sum(x["claims"] for x in m)
    lat = [x["latency_s"] for x in m if x["latency_s"] is not None]
    val_applicable = [x for x in m if x["validator_status"] not in (None, "skipped")]
    tokens = [x["total_tokens"] for x in m if x["total_tokens"] is not None]
    cost = [x["cost_usd"] for x in m if x["cost_usd"] is not None]

    confusion: Dict[str, Dict[str, int]] = {}
    for c in ev:
        e, a = c["expected"]["expected_intent"], str(c["actual"]["intent"])
        confusion.setdefault(e, {}).setdefault(a, 0)
        confusion[e][a] += 1

    # Negative control for the grounding metric: perturb every claim number by +/-10% and re-score.
    fp_n = fp_g = 0
    for p in payloads:
        for f in (1.1, 0.9):
            gg = M.number_grounding(M.perturb_numbers(p.get("answer") or {}, f), p.get("evidence") or [])
            fp_n += gg["numbers"]
            fp_g += gg["grounded"]

    judge_scores = [c["judge"]["faithfulness"] for c in ev if c.get("judge") and c["judge"]["faithfulness"] is not None]
    return {
        "n_cases": len(case_results), "n_evaluated": len(ev), "n_not_run": len(case_results) - len(ev),
        "case_pass_rate": M.mean(c["passed"] for c in ev),
        "routing_accuracy": M.mean(col("routing")),
        "ticker_f1": M.mean(col("ticker_f1")),
        "answer_type_accuracy": M.mean(col("answer_type_ok")),
        "schema_validity": M.mean(col("schema_valid")),
        "claims": claims,
        "citation_coverage": round(sum((x["citation_coverage"] or 0) * x["claims"] for x in m) / claims, 4) if claims else None,
        "citation_validity": M.mean(col("citation_validity")), "n_citation_validity": nn("citation_validity"),
        "numbers_checked": nums, "numbers_grounded": grounded,
        "number_grounding": round(grounded / nums, 4) if nums else None,
        "claims_fully_grounded": round(sum(x["claims_fully_grounded"] for x in m) / cwn, 4) if cwn else None,
        "grounding_false_positive_rate": round(fp_g / fp_n, 4) if fp_n else None, "grounding_control_numbers": fp_n,
        "forbidden_pass_rate": M.mean(x["forbidden_hits"] == 0 for x in m),
        "must_include_rate": M.mean(col("must_include_ok")), "n_must_include": nn("must_include_ok"),
        "verdict_determinism": M.mean(col("verdict_deterministic")),
        "verdict_matches_stored": M.mean(col("verdict_matches_stored")), "n_verdict_matches_stored": nn("verdict_matches_stored"),
        "verdict_consistency": M.mean(col("verdict_consistent")), "n_verdict_consistency": nn("verdict_consistent"),
        "rule_checker_pass_rate": M.mean(col("rule_checker_ok")), "n_rule_checker": nn("rule_checker_ok"),
        "llm_validator_pass_rate": M.mean(x["validator_status"] == "passed" for x in val_applicable), "n_llm_validator": len(val_applicable),
        "llm_validator_revisions": M.mean((x["validator_attempts"] or 1) > 1 for x in val_applicable),
        "latency_p50_s": M.percentile(lat, 50), "latency_p95_s": M.percentile(lat, 95), "latency_mean_s": M.mean(lat),
        "total_tokens_mean": M.mean(tokens), "cost_usd_total": round(sum(cost), 4) if cost else None,
        "judge_faithfulness": M.mean(judge_scores), "n_judged": len(judge_scores),
        "intent_confusion": confusion,
    }


METRIC_NOTES = {
    "routing_accuracy": "Share of cases whose orchestrator intent (after post-processing) equals the expected intent.",
    "ticker_f1": "Mean set-F1 of extracted NSE tickers vs expected (both empty counts as 1).",
    "schema_validity": "Share of answers that parse as the FinalAnswer Pydantic model.",
    "citation_coverage": "Claims with at least one citation / all claims (pooled over answers).",
    "citation_validity": "Mean over answers of: cited ids that exist in the evidence / all cited ids.",
    "number_grounding": "Numbers in claims found (within the claim's own rounding, ignoring sign/₹/commas, % <-> fraction) in the outputs of the evidence the claim cites / all checkable numbers. Window labels like '50-day', 'RSI (14)', dates are not checked. Lexical: derived numbers count as ungrounded.",
    "grounding_false_positive_rate": "Negative control: every claim number perturbed by +/-10%; share still 'grounded'. Measures how lenient the grounding matcher is.",
    "verdict_determinism": "Re-running the rule-based scorecard 3x on the recorded evidence gives identical output.",
    "verdict_consistency": "Answer verdict equals the best re-computed scorecard verdict (only answers with a verdict).",
    "rule_checker_pass_rate": "The app's deterministic checker (sections, citations exist, no foreign tickers, verdict present) re-run on the final answer.",
    "llm_validator_pass_rate": "Recorded status of the app's LLM Validation Agent (passed vs warning after the revision budget). Informational - not gating.",
    "case_pass_rate": "Cases where every applicable gating check passes (routing, tickers, answer type, schema, citations, grounding >= 90%, forbidden content, must_include, verdict consistency, rule checker).",
}


# --------------------------------------------------------------------------------------------
# Live mode
# --------------------------------------------------------------------------------------------


def parse_sse(text: str) -> List[dict]:
    """Parse a text/event-stream body into the list of JSON events."""
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue
    return events


def inprocess_chat_fn() -> ChatFn:
    """ChatFn that drives POST /agent/chat on the real FastAPI app via TestClient (makes real LLM calls)."""
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    client.__enter__()  # run lifespan (creates tables)
    r = client.post("/auth/mock-login", json={"email": "evals@finsight.local", "name": "Evals"})
    if r.status_code >= 400:
        raise RuntimeError(f"mock login failed: {r.status_code} {r.text[:200]}")

    def chat(question: str, history: List[str]) -> dict:
        session_id = None
        for turn in [*history, question]:
            started = time.perf_counter()
            resp = client.post("/agent/chat", json={"message": turn, "session_id": session_id})
            events = parse_sse(resp.text)
            final = next((e for e in events if e.get("type") == "final"), None)
            if final is None:
                err = next((e.get("content") for e in events if e.get("type") == "error"), resp.text[:200])
                raise RuntimeError(f"no final event: {err}")
            session_id = final["session_id"]
            payload = final["payload"]
            payload.setdefault("duration_s", round(time.perf_counter() - started, 1))
        return payload

    return chat


# --------------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------------


def _git_commit() -> Optional[str]:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def run(mode: str, cases: List[dict], fixtures: Optional[Dict[str, dict]] = None, chat_fn: Optional[ChatFn] = None,
        judge_llm: Optional[Callable] = None, run_id: Optional[str] = None, fixtures_path: Optional[str] = None) -> dict:
    """Score `cases` in replay mode (payloads looked up in `fixtures`) or live mode (payloads from `chat_fn`)."""
    results, payloads = [], []
    for case in cases:
        payload, reason = None, None
        if mode == "replay":
            payload = (fixtures or {}).get(_norm_q(case["question"]))
            if payload is None:
                reason = "no recorded answer for this question (live mode only)"
            elif case.get("history"):
                payload, reason = None, "follow-up case: recorded answer has no conversation context"
        else:
            try:
                payload = chat_fn(case["question"], case.get("history") or [])
            except Exception as e:  # keep going; record the failure
                reason = f"live call failed: {e}"
        if payload is None:
            results.append({"id": case["id"], "question": case["question"], "history": case.get("history") or [],
                            "status": "not_run", "reason": reason, "passed": None, "notes": case.get("notes"),
                            "expected": {k: case[k] for k in ("expected_intent", "expected_tickers", "expected_answer_type")}})
            continue
        payloads.append(payload)
        results.append(evaluate_case(case, payload, judge_llm))

    created = datetime.now(timezone.utc)
    return {
        "run_id": run_id or f"{mode}-{created.strftime('%Y%m%d-%H%M%S')}",
        "mode": mode, "created_at": created.isoformat(timespec="seconds"), "git_commit": _git_commit(),
        "dataset": {"path": "evals/dataset.yaml", "n_cases": len(cases)}, "fixtures": fixtures_path,
        "judge": judge_llm is not None,
        "summary": summarize(results, payloads), "metric_notes": METRIC_NOTES, "cases": results,
    }


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float) and 0 <= v <= 1:
        return f"{v:.1%}"
    return str(v)


def summary_markdown(res: dict) -> str:
    """Human-readable summary of a run."""
    s = res["summary"]
    keys = ["n_evaluated", "case_pass_rate", "routing_accuracy", "ticker_f1", "answer_type_accuracy", "schema_validity",
            "citation_coverage", "citation_validity", "number_grounding", "claims_fully_grounded", "grounding_false_positive_rate",
            "forbidden_pass_rate", "must_include_rate", "verdict_determinism", "verdict_consistency", "rule_checker_pass_rate",
            "llm_validator_pass_rate", "latency_p50_s", "latency_p95_s", "total_tokens_mean", "judge_faithfulness"]
    lines = [f"# Eval run {res['run_id']}", "", f"mode: {res['mode']} · commit {res['git_commit']} · {res['created_at']}", "",
             "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {_fmt(s.get(k))} |" for k in keys]
    lines += ["", "| case | status | passed | failed checks |", "|---|---|---|---|"]
    for c in res["cases"]:
        failed = ", ".join(k["name"] for k in c.get("checks", []) if k["gating"] and k["passed"] is False)
        lines.append(f"| {c['id']} | {c['status']} | {_fmt(c['passed'])} | {failed or ('-' if c['status'] == 'evaluated' else c.get('reason', ''))} |")
    return "\n".join(lines) + "\n"


def save(res: dict, out_dir: Path = RESULTS_DIR) -> Path:
    """Write <run_id>.json and <run_id>.md into out_dir; returns the JSON path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{res['run_id']}.json"
    p.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out_dir / f"{res['run_id']}.md").write_text(summary_markdown(res), encoding="utf-8")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["replay", "live"], default="replay")
    ap.add_argument("--fixtures", default=str(ROOT / "backend" / "tests" / "fixtures" / "answers.json"))
    ap.add_argument("--dataset", default=str(DATASET))
    ap.add_argument("--cases", help="comma-separated case ids to run (default: all)")
    ap.add_argument("--judge", action="store_true", help="add LLM-judge faithfulness (makes LLM calls)")
    ap.add_argument("--run-id")
    ap.add_argument("--out", default=str(RESULTS_DIR))
    a = ap.parse_args(argv)

    cases = load_dataset(a.dataset)
    if a.cases:
        want = set(a.cases.split(","))
        cases = [c for c in cases if c["id"] in want]
    judge_llm = None
    if a.judge:
        from evals.judge import default_judge_llm
        judge_llm = default_judge_llm()
    fixtures_rel = None
    if a.mode == "replay":
        fixtures = load_fixtures(a.fixtures)
        try:
            fixtures_rel = str(Path(a.fixtures).resolve().relative_to(ROOT))
        except ValueError:
            fixtures_rel = a.fixtures
        res = run("replay", cases, fixtures=fixtures, judge_llm=judge_llm, run_id=a.run_id, fixtures_path=fixtures_rel)
    else:
        res = run("live", cases, chat_fn=inprocess_chat_fn(), judge_llm=judge_llm, run_id=a.run_id)
    path = save(res, Path(a.out))
    print(summary_markdown(res))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
