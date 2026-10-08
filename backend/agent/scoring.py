"""
Deterministic signal scorecard.

The LLM does not choose BUY/SELL/HOLD. This module turns the raw tool outputs into
factor scores in [-1, +1], combines them with fixed weights, and maps the total
to a verdict. The same data always gives the same verdict, and every factor is
shown to the user, so the reasoning is auditable.
"""
from typing import Dict, List, Optional

BUY_THRESHOLD = 15    # score >= +15 -> BUY
SELL_THRESHOLD = -15  # score <= -15 -> SELL

WEIGHTS = {
    "trend": 1.5, "momentum": 1.0, "rsi": 0.75, "returns": 1.0, "prophet": 1.0,
    "xgboost": 1.0, "valuation": 1.0, "growth": 0.75, "sentiment": 0.75,
}


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _num(d: dict, key: str) -> Optional[float]:
    v = (d or {}).get(key)
    return float(v) if isinstance(v, (int, float)) else None


def _factor(name: str, label: str, value: float, reason: str, evidence_id: Optional[str]) -> dict:
    return {"name": name, "label": label, "score": round(_clamp(value), 2), "weight": WEIGHTS[name],
            "reason": reason, "evidence_id": evidence_id}


def score_ticker(ticker: str, outputs: Dict[str, dict], evidence_ids: Dict[str, str]) -> dict:
    """outputs: tool name -> output dict for this ticker; evidence_ids: tool name -> evidence id."""
    factors: List[dict] = []
    missing: List[str] = []
    tech = outputs.get("get_technical_indicators") or {}
    fund = outputs.get("get_fundamentals") or {}
    xgb = outputs.get("get_xgboost_signal") or {}
    proph = outputs.get("extract_prophet_features") or {}
    sent = outputs.get("get_sentiment_score") or {}
    eid = evidence_ids.get

    if tech.get("available"):
        e50, e200 = _num(tech, "ema_50"), _num(tech, "ema_200")
        price = _num(tech, "last_close")
        if price and e50 and e200:
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
        if rsi is not None:
            v = 1.0 if rsi < 30 else -1.0 if rsi > 70 else (50 - rsi) / 40
            note = "oversold" if rsi < 30 else "overbought" if rsi > 70 else "neutral range"
            factors.append(_factor("rsi", "RSI (14)", v, f"RSI {rsi:.0f} ({note})", eid("get_technical_indicators")))
        r3 = _num(tech, "return_3m_pct")
        if r3 is not None:
            factors.append(_factor("returns", "3-month return", r3 / 15, f"{r3:+.1f}% over 3 months", eid("get_technical_indicators")))
    else:
        missing.append("technical indicators")

    if proph.get("available"):
        d = proph.get("trend_direction")
        v = {"UPTREND": 1.0, "DOWNTREND": -1.0}.get(d, 0.0)
        factors.append(_factor("prophet", "Prophet trend", v, f"Fitted trend is {str(d).lower()}", eid("extract_prophet_features")))
    else:
        missing.append("Prophet trend")

    if xgb.get("available"):
        probs = xgb.get("probabilities") or {}
        acc = _num(xgb, "holdout_accuracy") or 0.0
        credibility = _clamp((acc - 0.33) / 0.33, 0.0, 1.0)  # 33% = random guess for 3 classes
        edge = (probs.get("BUY", 0) - probs.get("SELL", 0)) * 2
        factors.append(_factor("xgboost", "XGBoost model", edge * credibility,
                               f"{xgb.get('signal')} (BUY {probs.get('BUY', 0):.0%} / SELL {probs.get('SELL', 0):.0%}), "
                               f"holdout accuracy {acc:.0%} → weighted ×{credibility:.2f}", eid("get_xgboost_signal")))
    else:
        missing.append("XGBoost model")

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
    else:
        missing.append("fundamentals")

    if sent.get("available"):
        s = next((v for v in (_num(sent, k) for k in ("score", "avg_score_last_n", "latest_score")) if v is not None), 0.0)
        n = sent.get("n_articles")
        detail = f"Average sentiment {s:+.2f}" + (f" across {n} articles" if n else "")
        factors.append(_factor("sentiment", "News sentiment", s * 2, detail, eid("get_sentiment_score")))
    else:
        missing.append("news sentiment")

    total_w = sum(f["weight"] for f in factors)
    score = round(sum(f["score"] * f["weight"] for f in factors) / total_w * 100, 1) if total_w else 0.0
    verdict = "BUY" if score >= BUY_THRESHOLD else "SELL" if score <= SELL_THRESHOLD else "HOLD"

    # Confidence: how strongly and consistently the factors point one way, and how much data we had.
    direction = 1 if score > 0 else -1 if score < 0 else 0
    voting = [f for f in factors if abs(f["score"]) >= 0.15]
    agreement = (sum(1 for f in voting if (f["score"] > 0) == (direction > 0)) / len(voting)) if voting and direction else 0.5
    coverage = total_w / sum(WEIGHTS.values())
    strength = min(1.0, abs(score) / 50)
    confidence = round(0.25 + 0.35 * strength + 0.25 * agreement + 0.15 * coverage, 2)

    return {
        "ticker": ticker, "score": score, "verdict": verdict, "confidence": min(confidence, 0.9),
        "thresholds": {"buy": BUY_THRESHOLD, "sell": SELL_THRESHOLD},
        "factors": factors, "missing": missing, "coverage": round(coverage, 2),
    }


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
