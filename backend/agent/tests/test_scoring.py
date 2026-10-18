"""Scorecard hotfix (2026-10-18): NaN-safe inputs, honest coverage/confidence, INSUFFICIENT_DATA, no ML votes."""
import math

import numpy as np
import pandas as pd
import pytest

from backend.agent.scoring import (INSUFFICIENT, NO_FUNDAMENTALS_CONFIDENCE_CAP, WEIGHTS, build_scorecards,
                                   score_ticker, summarize)
from backend.providers.prices import clean_history, last_close

NAN = float("nan")
TECH = {"ticker": "X.NS", "available": True, "last_close": 110.0, "ema_50": 100.0, "ema_200": 90.0,
        "pct_vs_ema20": 2.0, "macd_histogram": 1.0, "rsi_14": 55.0, "return_3m_pct": 6.0}
FUND = {"ticker": "X.NS", "available": True, "pe_forward": 20.0, "pe_trailing": 22.0, "earnings_growth_pct": 15.0,
        "revenue_growth_pct": 10.0}
SENT = {"ticker": "X.NS", "available": True, "score": 0.1, "n_articles": 5}


def card(tech=TECH, fund=FUND, sent=SENT, **extra):
    outputs = {"get_technical_indicators": tech, "get_fundamentals": fund, "get_sentiment_score": sent, **extra}
    return score_ticker("X.NS", {k: v for k, v in outputs.items() if v is not None}, {})


def test_full_inputs_give_a_verdict_with_full_coverage():
    c = card()
    assert c["verdict"] in ("BUY", "SELL", "HOLD") and c["coverage"] == 1.0 and c["insufficient_reason"] is None
    assert {f["name"] for f in c["factors"]} == set(WEIGHTS)


@pytest.mark.parametrize("bad", [NAN, math.inf, -5.0, 0.0, None, "110"])
def test_invalid_price_gives_no_verdict(bad):
    c = card(tech={**TECH, "last_close": bad})
    assert c["verdict"] == INSUFFICIENT and c["confidence"] == 0.0
    assert "technical indicators" in c["missing"] and "price" in c["insufficient_reason"]
    assert not any(f["name"] in ("trend", "momentum", "rsi", "returns") for f in c["factors"])


def test_unavailable_technicals_give_no_verdict():
    assert card(tech={"ticker": "X.NS", "available": False})["verdict"] == INSUFFICIENT
    assert card(tech=None)["verdict"] == INSUFFICIENT


def test_nan_field_drops_only_its_factor_and_its_coverage():
    """Before the fix NaN became +1 (min(1, nan) == 1) and still counted as coverage."""
    c = card(tech={**TECH, "pct_vs_ema20": NAN, "rsi_14": NAN, "ema_200": NAN})
    names = {f["name"] for f in c["factors"]}
    assert names == {"returns", "valuation", "growth", "sentiment"}
    assert c["coverage"] == round(sum(WEIGHTS[n] for n in names) / sum(WEIGHTS.values()), 2)
    assert all(math.isfinite(f["score"]) for f in c["factors"])


def test_rsi_outside_0_100_is_ignored():
    assert "rsi" not in {f["name"] for f in card(tech={**TECH, "rsi_14": 140.0})["factors"]}


def test_sentiment_without_a_number_is_missing_not_neutral():
    c = card(sent={"ticker": "X.NS", "available": True, "score": NAN})
    assert "sentiment" not in {f["name"] for f in c["factors"]} and "news sentiment" in c["missing"]


def test_price_only_card_confidence_is_capped():
    strong = {**TECH, "pct_vs_ema20": 8.0, "return_3m_pct": 30.0, "rsi_14": 25.0}
    c = card(tech=strong, fund=None, sent=None)
    assert c["verdict"] == "BUY" and c["confidence"] <= NO_FUNDAMENTALS_CONFIDENCE_CAP
    assert "fundamentals" in c["missing"]


def test_fundamentals_with_only_nan_values_count_as_missing():
    c = card(fund={"ticker": "X.NS", "available": True, "pe_trailing": NAN, "revenue_growth_pct": NAN})
    assert "fundamentals" in c["missing"] and c["confidence"] <= NO_FUNDAMENTALS_CONFIDENCE_CAP


def test_xgboost_and_prophet_no_longer_vote():
    c = card(get_xgboost_signal={"ticker": "X.NS", "available": True, "probabilities": {"BUY": 1.0, "SELL": 0.0},
                                 "holdout_accuracy": 0.9},
             extract_prophet_features={"ticker": "X.NS", "available": True, "trend_direction": "UPTREND"})
    assert c == card()
    assert "xgboost" not in WEIGHTS and "prophet" not in WEIGHTS


def test_summarize_ignores_non_finite_factors():
    good = {"name": "trend", "score": 1.0, "weight": 1.5}
    assert summarize([good, {"name": "rsi", "score": NAN, "weight": 0.75}]) == summarize([good])
    assert summarize([])["verdict"] == INSUFFICIENT


def test_build_scorecards_is_deterministic():
    ev = [{"id": "R1", "tool": "get_technical_indicators", "output": TECH},
          {"id": "R2", "tool": "get_fundamentals", "output": FUND}]
    assert build_scorecards(ev, ["X.NS"]) == build_scorecards(ev, ["X.NS"])


# ---------------------------------------------------------------- shared price cleaning (A1)

def _frame(closes):
    idx = pd.date_range("2026-10-12", periods=len(closes), freq="B")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": 1000.0}, index=idx)


def test_clean_history_drops_the_unsettled_nan_row():
    df = _frame([100.0, 101.0, 102.0, NAN])
    out = clean_history(df)
    assert len(out) == 3 and out["Close"].iloc[-1] == 102.0
    assert last_close(df) == 102.0


def test_clean_history_drops_non_positive_and_duplicate_rows():
    df = _frame([100.0, 0.0, -1.0, 103.0])
    df = pd.concat([df, df.iloc[[-1]].assign(Close=104.0)])
    out = clean_history(df)
    assert list(out["Close"]) == [100.0, 104.0] and out.index.is_monotonic_increasing


def test_clean_history_handles_empty_and_none():
    assert clean_history(None).empty and clean_history(pd.DataFrame()).empty
    assert last_close(_frame([NAN, np.inf])) is None


def test_technicals_never_read_the_nan_row(monkeypatch):
    from backend.agent.tools import technical
    closes = list(np.linspace(100, 130, 260)) + [NAN]
    monkeypatch.setattr(technical, "get_history", lambda t, period="1y": clean_history(_frame(closes)))
    out = technical.get_technical_indicators("X.NS")
    assert out["available"] and out["last_close"] == 130.0 and math.isfinite(out["rsi_14"])
