"""Tests for the eval runner: replay over the real fixtures, live mode with a fake chat function, the judge with a fake LLM."""
import json
from pathlib import Path

import pytest

from evals import run as R
from evals.judge import judge_answer

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "backend" / "tests" / "fixtures" / "answers.json"


@pytest.fixture(scope="module")
def replay():
    return R.run("replay", R.load_dataset(), fixtures=R.load_fixtures(FIX), run_id="t-replay")


def test_dataset_is_well_formed():
    cases = R.load_dataset()
    assert 20 <= len(cases) <= 40
    intents = {c["expected_intent"] for c in cases}
    assert intents == {"research", "comparison", "sentiment", "portfolio", "ideas", "clarify", "direct_answer"}
    assert any(c["history"] for c in cases), "needs follow-up cases"
    ids = {c["id"] for c in cases}
    assert {"research-policybazaar", "research-lt"} <= ids


def test_replay_scores_every_fixture(replay):
    s = replay["summary"]
    assert s["n_evaluated"] == 6 and s["n_cases"] == len(R.load_dataset())
    assert s["routing_accuracy"] == 1.0 and s["schema_validity"] == 1.0
    assert s["verdict_determinism"] == 1.0
    assert s["numbers_checked"] > 40 and 0.0 <= s["number_grounding"] <= 1.0
    assert s["grounding_false_positive_rate"] < 0.1
    assert s["latency_p50_s"] is not None and s["latency_p95_s"] >= s["latency_p50_s"]
    assert s["total_tokens_mean"] is None  # not recorded in fixtures -> reported as n/a, not 0


def test_replay_case_details(replay):
    by = {c["id"]: c for c in replay["cases"]}
    assert by["research-lt"]["status"] == "not_run"
    pb = by["research-policybazaar"]
    assert pb["status"] == "evaluated" and pb["scorecard_recheck"]["matches_stored"] is True
    hi = by["direct-hi"]
    assert hi["passed"] is True and hi["metrics"]["claims"] == 0 and hi["metrics"]["citation_coverage"] is None
    # portfolio answer has a single section -> app's rule checker and must_include flag it
    port = {c["name"]: c for c in by["portfolio-health"]["checks"]}
    assert port["rule_checker"]["passed"] is False and port["must_include"]["passed"] is False


def test_save_writes_json_and_markdown(tmp_path, replay):
    p = R.save(replay, tmp_path)
    data = json.loads(p.read_text())
    assert data["run_id"] == "t-replay" and (tmp_path / "t-replay.md").exists()


def test_live_mode_with_fake_chat_fn():
    fixtures = R.load_fixtures(FIX)
    calls = []

    def fake_chat(question, history):
        calls.append((question, tuple(history)))
        if "explode" in question:
            raise RuntimeError("boom")
        return fixtures[R._norm_q("Compare TCS and Infosys")]

    cases = [c for c in R.load_dataset() if c["id"] in ("compare-tcs-infy", "followup-compare-icici")]
    cases.append({**cases[0], "id": "x", "question": "explode", "history": []})
    res = R.run("live", cases, chat_fn=fake_chat)
    by = {c["id"]: c for c in res["cases"]}
    assert ("compare it with ICICI Bank", ("how is SBI",)) in calls
    assert by["compare-tcs-infy"]["status"] == "evaluated"
    assert by["followup-compare-icici"]["metrics"]["ticker_f1"] == 0.0
    assert by["x"]["status"] == "not_run" and "boom" in by["x"]["reason"]


def test_parse_sse():
    body = 'data: {"type": "step"}\n\ndata: not-json\n\ndata: {"type": "final", "payload": {"a": 1}}\n\n'
    assert [e["type"] for e in R.parse_sse(body)] == ["step", "final"]


def test_judge_with_fake_llm():
    payload = R.load_fixtures(FIX)[R._norm_q("how is policy bazaar looking")]
    seen = []

    def fake_llm(system, user):
        seen.append(user)
        return {"label": "partial" if "PEG" in user else "supported", "reason": "ok"}

    j = judge_answer(payload["answer"], payload["evidence"], fake_llm)
    n = sum(len(s["claims"]) for s in payload["answer"]["sections"])
    assert len(j["claims"]) == n == len(seen)
    assert j["counts"]["partial"] >= 1 and 0.9 < j["faithfulness"] < 1.0
    assert "EVIDENCE:" in seen[0] and "CLAIM:" in seen[0]


def test_judge_handles_errors_and_missing_citations():
    a = {"answer_type": "ideas", "headline": "h", "sections": [{"title": "t", "claims": [
        {"text": "x", "citations": []}, {"text": "y", "citations": ["R1"]}]}]}

    def broken(system, user):
        raise RuntimeError("rate limit")

    j = judge_answer(a, [{"id": "R1", "tool": "t", "output": {}}], broken)
    assert j["counts"] == {"supported": 0, "partial": 0, "unsupported": 1, "error": 1}
    assert j["faithfulness"] == 0.0


def test_run_with_judge_flag_adds_nongating_check():
    fixtures = R.load_fixtures(FIX)
    case = next(c for c in R.load_dataset() if c["id"] == "research-policybazaar")
    res = R.run("replay", [case], fixtures=fixtures, judge_llm=lambda s, u: {"label": "unsupported", "reason": "x"})
    c = res["cases"][0]
    jc = next(k for k in c["checks"] if k["name"] == "judge_faithfulness")
    assert jc["passed"] is False and jc["gating"] is False and c["passed"] is True
    assert res["summary"]["judge_faithfulness"] == 0.0
