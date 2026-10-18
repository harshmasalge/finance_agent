"""Unit tests for weighting-instruction parsing and scorecard recomputation."""
import json
from pathlib import Path

import pytest

from backend.review.reweight import compute, parse_weighting, reweight_card

FIXTURES = json.loads((Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "answers.json").read_text(encoding="utf-8"))
CARD = next(f for f in FIXTURES if f["payload"].get("scorecards"))["payload"]["scorecards"][0]


def test_compute_reproduces_stored_card():
    # Cards stored before 2026-10-18 still carry XGBoost/Prophet factors: score and verdict reproduce exactly;
    # confidence can differ slightly because coverage is now measured against the smaller current weight set.
    c = compute(CARD)
    assert (c["score"], c["verdict"]) == (CARD["score"], CARD["verdict"])


def test_compute_reproduces_current_scorecards():
    from backend.agent.scoring import build_scorecards
    for f in FIXTURES:
        p = f["payload"]
        for card in build_scorecards(p.get("evidence") or [], p.get("tickers") or []):
            c = compute(card)
            assert (c["score"], c["verdict"], c["confidence"], c["coverage"]) == \
                (card["score"], card["verdict"], card["confidence"], card["coverage"])


@pytest.mark.parametrize("text,expected", [
    ("ignore the XGBoost signal", {"xgboost": None}),
    ("weight valuation higher", {"valuation": 2.0}),
    ("Valuation should be weighted lower", {"valuation": 0.5}),
    ("set RSI weight to 0.25", {"rsi": 0.25}),
    ("the prophet trend should not count", {"prophet": None}),
    ("Ignore the RSI; double valuation", {"rsi": None, "valuation": 2.0}),
    ("drop the long-term trend factor", {"trend": None}),
    ("RSI should be 45", {}),
    ("Detection Index should be 7, not 4", {}),
    ("give more weight to news sentiment", {}),  # factor missing from this card
])
def test_parse_weighting(text, expected):
    assert parse_weighting(text, [CARD]) == expected


def test_reweight_card_records_changes():
    new, changes = reweight_card(CARD, {"xgboost": None, "unknown": 3})
    assert new["score"] == -14.3 and new["verdict"] == "HOLD" and new["overrides"] == {"xgboost": 0.0}
    assert changes == [{"factor": "xgboost", "label": "XGBoost model", "before": 1.0, "after": 0.0}]
    assert CARD["factors"][5]["weight"] == 1.0  # input untouched
