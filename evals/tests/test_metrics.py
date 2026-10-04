"""Unit tests for evals.metrics (pure functions, no network, no LLM)."""
import json
from pathlib import Path

import pytest

from evals import metrics as M

FIXTURES = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "answers.json"


def ans(*claims, answer_type="stock_analysis", verdict=None):
    return {"answer_type": answer_type, "headline": "h", "verdict": verdict, "verdict_ticker": None, "confidence": None,
            "sections": [{"title": "S", "claims": [{"text": t, "citations": c} for t, c in claims]}], "data_gaps": []}


EV = [
    {"id": "R1", "tool": "get_fundamentals", "output": {"ticker": "TECHM.NS", "pe_trailing": 26.52708, "pe_forward": 17.462591,
                                                        "last_close": 1533, "market_cap_cr": 145286.0}},
    {"id": "R2", "tool": "get_xgboost_signal", "output": {"ticker": "TECHM.NS", "probabilities": {"BUY": 0.54}, "pct_vs_ema20": -33.78}},
    {"id": "S1", "tool": "get_recent_headlines", "output": {"headlines": [{"title": "Shares fall 4.5% after Q2 results"}]}},
]


# ---------------- number extraction ----------------

@pytest.mark.parametrize("text,value,decimals,pct", [
    ("₹1,533.00", 1533.0, 2, False),
    ("Rs. 1,00,000", 100000.0, 0, False),
    ("26.53", 26.53, 2, False),
    ("-38.0%", -38.0, 1, True),
    ("54 per cent", 54.0, 0, True),
    ("−2.5%", -2.5, 1, True),
])
def test_extract_numbers_formats(text, value, decimals, pct):
    [tok] = M.extract_numbers(text)
    assert tok.value == pytest.approx(value) and tok.decimals == decimals and tok.is_pct == pct


def test_extract_numbers_exemptions():
    toks = M.extract_numbers("Below its 50- and 200-day EMAs, RSI (14) at 18.2, 3-month return, NIFTY 50, as of 2026-10-01")
    checked = [t.value for t in toks if not t.exempt]
    assert checked == [18.2]


def test_sentence_final_period_and_dates_not_negative():
    toks = M.extract_numbers("P/E is 26.53. On 2026-10-01 it closed")
    assert [t.value for t in toks if not t.exempt] == [26.53]


# ---------------- tolerant matching ----------------

@pytest.mark.parametrize("claim,candidate,ok", [
    ("₹1,533.00", 1533, True),
    ("₹1,533", 1533.4, True),
    ("26.53", 26.52708, True),
    ("26.5", 26.52708, True),
    ("27", 26.52708, True),          # integer rounding is within half a unit
    ("26.54", 26.52708, False),
    ("54%", 0.54, True),               # percentage vs fraction
    ("54%", 54.0, True),
    ("33.78% below", -33.78, True),    # sign carried by words
    ("8.26%", -8.26, True),
    ("1,543", 1533, False),
    ("0.5", 0.54, True),
    ("0.6", 0.54, False),
])
def test_number_matches(claim, candidate, ok):
    tok = M.extract_numbers(claim)[0]
    assert M.number_matches(tok, candidate) is ok


def test_evidence_numbers_walks_nested_and_strings():
    nums = M.evidence_numbers({"a": 1, "b": [2.5, {"c": "price fell 4.5% to ₹1,200"}], "d": True, "e": None})
    assert sorted(nums) == [1.0, 2.5, 4.5, 1200.0]


def test_number_grounding_counts_and_ungrounded():
    a = ans(("Trailing P/E is 26.53 and forward P/E 17.46.", ["R1"]),
            ("BUY probability is 54% and price is 33.8% below the 20-day EMA.", ["R2"]),
            ("Market cap is ₹1,45,286 crore.", ["R1"]),
            ("Revenue grew 12.4% last year.", ["R1"]),          # not in evidence -> ungrounded
            ("Shares fell 4.5% after Q2 results.", ["R1"]),      # number is in S1 but S1 is not cited
            ("A claim without numbers.", ["R1"]))
    g = M.number_grounding(a, EV)
    assert g["numbers"] == 7 and g["grounded"] == 5
    assert g["claims_with_numbers"] == 5 and g["claims_fully_grounded"] == 3
    assert {u["number"] for u in g["ungrounded"]} == {"12.4%", "4.5%"}


def test_number_grounding_no_numbers_is_none():
    g = M.number_grounding(ans(("No numbers here.", ["R1"])), EV)
    assert g["rate"] is None and g["claim_rate"] is None


def test_perturbation_breaks_grounding():
    a = ans(("Trailing P/E is 26.53, price ₹1,533.", ["R1"]))
    assert M.number_grounding(a, EV)["rate"] == 1.0
    assert M.number_grounding(M.perturb_numbers(a, 1.1), EV)["rate"] == 0.0


# ---------------- routing / tickers ----------------

def test_routing():
    assert M.routing_correct("research", "research")
    assert not M.routing_correct("research", "clarify")
    assert not M.routing_correct("research", None)


def test_ticker_prf():
    assert M.ticker_prf(["TCS.NS", "INFY.NS"], ["tcs", "INFY.NS"]) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert M.ticker_prf([], []) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    r = M.ticker_prf(["TCS.NS", "INFY.NS"], ["TCS.NS", "WIPRO.NS", "HCLTECH.NS"])
    assert r["precision"] == pytest.approx(1 / 3, abs=1e-4) and r["recall"] == 0.5 and r["f1"] == pytest.approx(0.4)
    assert M.ticker_prf(["LT.NS"], [])["f1"] == 0.0
    assert M.ticker_prf([], ["LT.NS"])["f1"] == 0.0


# ---------------- schema / citations ----------------

def test_schema_valid():
    assert M.schema_valid(ans(("x", ["R1"])))[0]
    ok, err = M.schema_valid({"headline": "missing answer_type"})
    assert not ok and err
    assert not M.schema_valid({**ans(("x", [])), "verdict": "STRONG BUY"})[0]


def test_citation_coverage_and_validity():
    a = ans(("a", ["R1"]), ("b", []), ("c", ["R9", "R2"]), ("d", ["S1"]))
    assert M.citation_coverage(a) == 0.75
    assert M.citation_validity(a, EV) == 0.75
    assert M.invalid_citations(a, EV) == ["R9"]
    empty = ans(answer_type="general")
    empty["sections"] = []
    assert M.citation_coverage(empty) is None and M.citation_validity(empty, EV) is None


# ---------------- forbidden / required ----------------

def test_forbidden_content():
    assert M.forbidden_content("TCS.NS and RELIANCE.BO look fine") == []
    assert M.forbidden_content("Compare with AAPL and NVDA") == ["AAPL", "NVDA"]
    assert M.forbidden_content("Listed as INFY.N in New York") == ["INFY.N"]
    assert M.forbidden_content("This is guaranteed", ["guaranteed"]) == ["guaranteed"]
    assert M.forbidden_content("M&M.NS and BAJAJ-AUTO.NS") == []


def test_missing_required_alternatives():
    assert M.missing_required("Verdict: HOLD. Why this verdict", ["why this verdict", "BUY|SELL|HOLD"]) == []
    assert M.missing_required("Overview only", ["Allocation|concentration"]) == ["Allocation|concentration"]


# ---------------- verdict determinism ----------------

TECH = {"ticker": "X.NS", "available": True, "last_close": 110, "ema_50": 100, "ema_200": 90, "pct_vs_ema20": 3.0,
        "macd_histogram": 1.2, "rsi_14": 55, "return_3m_pct": 12}


def test_verdict_determinism_and_consistency():
    ev = [{"id": "R1", "tool": "get_technical_indicators", "output": TECH}]
    d = M.verdict_determinism(ev, ["X.NS"], None, {"verdict": "BUY"})
    assert d["deterministic"] and d["n_cards"] == 1 and d["matches_stored"] is None
    assert d["recomputed"][0]["verdict"] == "BUY" and d["answer_consistent"] is True
    d2 = M.verdict_determinism(ev, ["X.NS"], [{"ticker": "X.NS", "score": 1.0, "verdict": "HOLD", "confidence": 0.3}], {"verdict": "HOLD"})
    assert d2["matches_stored"] is False and d2["answer_consistent"] is False
    assert M.verdict_determinism([], [], None, {"verdict": None})["answer_consistent"] is None


def test_policybazaar_fixture_scorecard_reproduces():
    rec = next(r for r in json.loads(FIXTURES.read_text()) if "policy" in r["question"])
    p = rec["payload"]
    d = M.verdict_determinism(p["evidence"], p["tickers"], p["scorecards"], p["answer"])
    assert d["deterministic"] and d["matches_stored"] is True and d["answer_consistent"] is True


# ---------------- stats ----------------

def test_percentile_and_mean():
    assert M.percentile([], 50) is None
    assert M.percentile([5], 95) == 5
    assert M.percentile([1, 2, 3, 4], 50) == 2.5
    assert M.percentile([10, 20, 30, 40, 50], 95) == pytest.approx(48.0)
    assert M.mean([True, False, None, True]) == pytest.approx(0.6667, abs=1e-4)
    assert M.mean([None]) is None


def test_usage_from_payload():
    assert M.usage_from_payload({})["total_tokens"] is None
    u = M.usage_from_payload({"usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "cost_usd": 0.01}})
    assert u == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost_usd": 0.01}
