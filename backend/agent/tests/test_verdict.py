"""Verdict gating in synthesis (B1, B5): no verdict on invalid inputs or a failed research agent."""
from backend.agent.scoring import INSUFFICIENT
from backend.agent.synthesis import FAILED_AGENT_CONFIDENCE_CAP, _verdict_block


def _card(ticker, score, verdict, confidence=0.8, reason=None):
    return {"ticker": ticker, "score": score, "verdict": verdict, "confidence": confidence, "insufficient_reason": reason}


OK = {"agent": "Sentiment Agent", "summary": "fine"}


def test_best_scorecard_sets_the_verdict():
    b = _verdict_block({"sentiment_output": OK}, [_card("A.NS", 20, "BUY"), _card("B.NS", -3, "HOLD")])
    assert (b["verdict"], b["ticker"], b["confidence"], b["gap"]) == ("BUY", "A.NS", 0.8, None)


def test_no_scorecard_means_no_verdict():
    b = _verdict_block({"target_tickers": ["A.NS"]}, [])
    assert b["verdict"] == INSUFFICIENT and b["confidence"] is None and b["ticker"] == "A.NS"


def test_any_invalid_card_means_no_verdict():
    cards = [_card("A.NS", 30, "BUY"), _card("B.NS", 0, INSUFFICIENT, 0.0, "No valid current price")]
    b = _verdict_block({}, cards)
    assert b["verdict"] == INSUFFICIENT and b["ticker"] == "B.NS" and "No valid current price" in b["reason"]


def test_failed_research_agent_means_no_verdict():
    state = {"research_output": {"agent": "Research Agent", "failed": True}}
    b = _verdict_block(state, [_card("A.NS", 30, "BUY")])
    assert b["verdict"] == INSUFFICIENT and "research agent failed" in b["reason"].lower()


def test_failed_supporting_agent_caps_confidence():
    state = {"sentiment_output": {"agent": "Sentiment Agent", "failed": True},
             "risk_output": {"agent": "Risk Agent", "failed": True}}
    b = _verdict_block(state, [_card("A.NS", 30, "BUY", 0.85)])
    assert b["verdict"] == "BUY" and b["confidence"] == FAILED_AGENT_CONFIDENCE_CAP
    assert "Sentiment Agent and Risk Agent failed" in b["gap"]
