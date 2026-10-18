"""
Deterministic signal scorecard.

The LLM does not choose BUY/SELL/HOLD. This module turns the raw tool outputs into
factor scores in [-1, +1], combines them with fixed weights, and maps the total
to a verdict. The same data always gives the same verdict, and every factor is
shown to the user, so the reasoning is auditable.
"""
import math
from typing import Dict, List, Optional

BUY_THRESHOLD = 15    # score >= +15 -> BUY
SELL_THRESHOLD = -15  # score <= -15 -> SELL
INSUFFICIENT = "INSUFFICIENT_DATA"  # no verdict: the inputs a verdict needs are missing or invalid

# The per-request XGBoost classifier and the Prophet trend were removed on 2026-10-18: both were
# tested out of sample and had no predictive value (docs/xgboost_review.md, docs/ml_forecasting_decision.md).
WEIGHTS = {
    "trend": 1.5, "momentum": 1.0, "rsi": 0.75, "returns": 1.0,
    "valuation": 1.0, "growth": 0.75, "sentiment": 0.75,
}
FUNDAMENTAL_FACTORS = ("valuation", "growth")
MAX_CONFIDENCE = 0.9
NO_FUNDAMENTALS_CONFIDENCE_CAP = 0.6  # a price-only scorecard never claims more than this


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _num(d: dict, key: str) -> Optional[float]:
    """A finite number from a tool output, else None. NaN/inf (e.g. an unsettled yfinance row) count as missing."""
    v = (d or {}).get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _factor(name: str, label: str, value: float, reason: str, evidence_id: Optional[str]) -> dict:
    return {"name": name, "label": label, "score": round(_clamp(value), 2), "weight": WEIGHTS[name],
            "reason": reason, "evidence_id": evidence_id}


def _valid(f: dict) -> bool:
    s, w = f.get("score"), f.get("weight")
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (s, w))


def summarize(factors: List[dict], thresholds: Optional[dict] = None, insufficient_reason: Optional[str] = None) -> dict:
    """Score, verdict, confidence and coverage from a list of factors.

    Shared by `score_ticker` and the analyst re-weighting in `backend.review.reweight`, so both use one formula.
    Only finite factors count, and coverage is the share of the full weight that valid factors carry.
    """
    th = thresholds or {"buy": BUY_THRESHOLD, "sell": SELL_THRESHOLD}
    valid = [f for f in factors if _valid(f)]
    total_w = sum(f["weight"] for f in valid)
    score = round(sum(f["score"] * f["weight"] for f in valid) / total_w * 100, 1) if total_w else 0.0
    verdict = "BUY" if score >= th["buy"] else "SELL" if score <= th["sell"] else "HOLD"

    # Confidence: how strongly and consistently the factors point one way, and how much data we had.
    direction = 1 if score > 0 else -1 if score < 0 else 0
    voting = [f for f in valid if abs(f["score"]) >= 0.15 and f["weight"] > 0]
    agreement = (sum(1 for f in voting if (f["score"] > 0) == (direction > 0)) / len(voting)) if voting and direction else 0.5
    coverage = min(1.0, total_w / sum(WEIGHTS.values()))
    strength = min(1.0, abs(score) / 50)
    confidence = min(round(0.25 + 0.35 * strength + 0.25 * agreement + 0.15 * coverage, 2), MAX_CONFIDENCE)
    if not any(f["name"] in FUNDAMENTAL_FACTORS and f["weight"] > 0 for f in valid):
        confidence = min(confidence, NO_FUNDAMENTALS_CONFIDENCE_CAP)
    if insufficient_reason or total_w == 0:
        verdict, confidence = INSUFFICIENT, 0.0
    return {"score": score, "verdict": verdict, "confidence": confidence, "coverage": round(coverage, 2),
            "thresholds": th, "insufficient_reason": insufficient_reason or (None if total_w else "No usable factors.")}


def score_ticker(ticker: str, outputs: Dict[str, dict], evidence_ids: Dict[str, str]) -> dict:
    """outputs: tool name -> output dict for this ticker; evidence_ids: tool name -> evidence id."""
    factors: List[dict] = []
    missing: List[str] = []
    insufficient_reason: Optional[str] = None
    tech = outputs.get("get_technical_indicators") or {}
    fund = outputs.get("get_fundamentals") or {}
    sent = outputs.get("get_sentiment_score") or {}
    eid = evidence_ids.get

    price = _num(tech, "last_close") if tech.get("available") else None
    if price is None or price <= 0:
        missing.append("technical indicators")
        insufficient_reason = ("No valid current price: technical indicators were unavailable or invalid, "
                               "so no BUY/SELL/HOLD verdict is given.")
    else:
        e50, e200 = _num(tech, "ema_50"), _num(tech, "ema_200")
        if e50 and e200 and e50 > 0 and e200 > 0:
            above = (price > e50) + (price > e200)
            v = {2: 1.0, 1: 0.0, 0: -1.0}[above]
            desc = {2: "above both its 50- and 200-day EMAs", 1: "between its 50- and 200-day EMAs", 0: "below both its 50- and 200-day EMAs"}[above]
            factors.append(_factor("trend", "Long-term trend", v, f"Price ₹{price:,.0f} is {desc}", eid("get_technical_indicators")))
        p20, macd = _num(tech, "pct_vs_ema20"), _num(tech, "macd_histogram")
        if p20 is not None and macd is not None:
            v = 0.6 * _clamp(p20 / 5) + 0.4 * (1 if macd > 0 else -1)
            factors.append(_factor("momentum", "Short-term momentum", v,
                                   f"{p20:+.1f}% vs 20-day EMA, MACD histogram {macd:+.2f}", eid("get_technical_indicators")))
        rsi = _num(tech, "rsi_14")
        if rsi is not None and 0 <= rsi <= 100:
            v = 1.0 if rsi < 30 else -1.0 if rsi > 70 else (50 - rsi) / 40
            note = "oversold" if rsi < 30 else "overbought" if rsi > 70 else "neutral range"
            factors.append(_factor("rsi", "RSI (14)", v, f"RSI {rsi:.0f} ({note})", eid("get_technical_indicators")))
        r3 = _num(tech, "return_3m_pct")
        if r3 is not None:
            factors.append(_factor("returns", "3-month return", r3 / 15, f"{r3:+.1f}% over 3 months", eid("get_technical_indicators")))

    if fund.get("available"):
        pe_f, pe_t, eg = _num(fund, "pe_forward"), _num(fund, "pe_trailing"), _num(fund, "earnings_growth_pct")
        if pe_f and pe_f > 0 and eg is not None and eg >= 5:
            peg = pe_f / eg
            v = 1.0 if peg < 1 else 0.4 if peg < 1.5 else 0.0 if peg < 2 else -0.5 if peg < 3 else -1.0
            if pe_t and pe_t < 15:
                v = max(v, 0.3)  # a low absolute P/E is never "expensive"
            factors.append(_factor("valuation", "Valuation (PEG)", v,
                                   f"Forward P/E {pe_f:.1f} ÷ earnings growth {eg:.1f}% = PEG {peg:.2f}", eid("get_fundamentals")))
        elif pe_t and pe_t > 0:
            v = 0.6 if pe_t < 15 else 0.2 if pe_t < 25 else -0.2 if pe_t < 40 else -0.6
            factors.append(_factor("valuation", "Valuation (P/E)", v, f"Trailing P/E {pe_t:.1f}", eid("get_fundamentals")))
        rg = _num(fund, "revenue_growth_pct")
        if rg is not None:
            factors.append(_factor("growth", "Revenue growth", (rg - 5) / 15, f"Revenue growth {rg:+.1f}% YoY", eid("get_fundamentals")))
    if not any(f["name"] in FUNDAMENTAL_FACTORS for f in factors):
        missing.append("fundamentals")

    s = next((v for v in (_num(sent, k) for k in ("score", "avg_score_last_n", "latest_score")) if v is not None), None) \
        if sent.get("available") else None
    if s is not None:
        n = sent.get("n_articles")
        detail = f"Average sentiment {s:+.2f}" + (f" across {n} articles" if n else "")
        factors.append(_factor("sentiment", "News sentiment", s * 2, detail, eid("get_sentiment_score")))
    else:
        missing.append("news sentiment")

    factors = [f for f in factors if _valid(f)]
    return {"ticker": ticker, **summarize(factors, insufficient_reason=insufficient_reason),
            "factors": factors, "missing": missing}


def build_scorecards(evidence: List[dict], tickers: List[str]) -> List[dict]:
    """Group the research/sentiment evidence by ticker and score each one."""
    cards = []
    for t in tickers:
        outputs: Dict[str, dict] = {}
        ids: Dict[str, str] = {}
        for e in evidence:
            out = e.get("output") or {}
            if isinstance(out, dict) and out.get("ticker") == t and e["tool"] not in ("get_position",):
                outputs[e["tool"]] = out
                ids[e["tool"]] = e["id"]
        if outputs:
            cards.append(score_ticker(t, outputs, ids))
    return cards
