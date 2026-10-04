"""Deterministic scorecard re-weighting for analyst weighting corrections.

Recomputes a stored scorecard from its own factors with weight overrides, using the same
formula as `backend.agent.scoring.score_ticker` (score = sum(score*w) / sum(w) * 100, verdict
from the card's thresholds, same confidence formula), without re-running any tools and
without editing the protected scoring module.
"""
import copy
import re
from typing import Dict, List, Optional, Tuple

from backend.agent.scoring import BUY_THRESHOLD, SELL_THRESHOLD, WEIGHTS

Overrides = Dict[str, Optional[float]]

# Phrases an analyst may use for each factor, longest first so "prophet trend" wins over "trend".
FACTOR_ALIASES: Dict[str, List[str]] = {
    "prophet": ["prophet trend", "prophet"],
    "trend": ["long-term trend", "long term trend", "ema trend", "trend"],
    "momentum": ["short-term momentum", "momentum", "macd"],
    "rsi": ["rsi"],
    "returns": ["3-month return", "3 month return", "three-month return", "past returns", "returns"],
    "xgboost": ["xgboost", "xgb", "ml model", "machine learning model", "ml signal"],
    "valuation": ["valuation", "peg", "p/e", "pe ratio"],
    "growth": ["revenue growth", "growth"],
    "sentiment": ["news sentiment", "sentiment", "news"],
}

_IGNORE = r"(ignore|ignoring|drop|exclude|remove|disregard|don'?t (?:use|count|consider)|do not (?:use|count|consider)|zero(?:\s+out)?|no weight (?:on|for|to)|(?:should|must|does|do)\s*(?:n'?t|not)\s+(?:count|matter|be used|be counted|be considered))"
_UP = r"(higher|more|up|increase|double|heavier|heavily|more heavily|stronger)"
_DOWN = r"(lower|less|down|decrease|reduce|halve|lighter|lightly|downweight|down-weight|weaker)"


def compute(card: dict) -> dict:
    """Recompute score, verdict, confidence and coverage of `card` from its factors (in place copy)."""
    card = copy.deepcopy(card)
    factors = card.get("factors") or []
    th = card.get("thresholds") or {"buy": BUY_THRESHOLD, "sell": SELL_THRESHOLD}
    total_w = sum(f["weight"] for f in factors)
    score = round(sum(f["score"] * f["weight"] for f in factors) / total_w * 100, 1) if total_w else 0.0
    verdict = "BUY" if score >= th["buy"] else "SELL" if score <= th["sell"] else "HOLD"
    direction = 1 if score > 0 else -1 if score < 0 else 0
    voting = [f for f in factors if abs(f["score"]) >= 0.15 and f["weight"] > 0]
    agreement = (sum(1 for f in voting if (f["score"] > 0) == (direction > 0)) / len(voting)) if voting and direction else 0.5
    coverage = min(1.0, total_w / sum(WEIGHTS.values()))
    strength = min(1.0, abs(score) / 50)
    confidence = round(0.25 + 0.35 * strength + 0.25 * agreement + 0.15 * coverage, 2)
    card.update(score=score, verdict=verdict, confidence=min(confidence, 0.9), coverage=round(coverage, 2))
    return card


def reweight_card(card: dict, overrides: Overrides) -> Tuple[dict, List[dict]]:
    """Apply `{factor: new_weight | None}` (None = ignore, i.e. weight 0) and recompute.

    Returns the new card and a list of `{factor, label, before, after}` weight changes.
    Unknown factor names are ignored. The original weight is kept as `base_weight`.
    """
    new = copy.deepcopy(card)
    changes = []
    for f in new.get("factors") or []:
        if f["name"] not in overrides:
            continue
        w = overrides[f["name"]]
        w = 0.0 if w is None else max(0.0, float(w))
        if abs(w - f["weight"]) < 1e-9:
            continue
        f.setdefault("base_weight", f["weight"])
        changes.append({"factor": f["name"], "label": f.get("label", f["name"]), "before": f["weight"], "after": round(w, 3)})
        f["weight"] = round(w, 3)
        f["analyst_override"] = True
    new = compute(new)
    applied = dict(new.get("overrides") or {})
    applied.update({c["factor"]: c["after"] for c in changes})
    if applied:
        new["overrides"] = applied
    return new, changes


def _find_factor(segment: str, available: List[str]) -> Optional[str]:
    """Return the factor whose alias appears earliest in `segment` (longest alias wins on ties)."""
    best: Optional[Tuple[int, int, str]] = None
    for name, aliases in FACTOR_ALIASES.items():
        if name not in available:
            continue
        for a in aliases:
            m = re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", segment)
            if m:
                key = (m.start(), -len(a), name)
                if best is None or key < best:
                    best = key
    return best[2] if best else None


def parse_weighting(text: str, cards: List[dict]) -> Overrides:
    """Detect plain-English weighting instructions, e.g. "ignore the XGBoost signal",
    "weight valuation higher", "halve momentum", "set RSI weight to 0.5".

    Multipliers are relative to the factor's current weight on the first card that has it.
    Returns {} when the text is not a weighting instruction.
    """
    t = text.lower()
    available = sorted({f["name"] for c in cards for f in c.get("factors") or []})
    current = {}
    for c in cards:
        for f in c.get("factors") or []:
            current.setdefault(f["name"], f["weight"])
    if not available:
        return {}
    out: Overrides = {}
    for seg in re.split(r"\.(?!\d)|[;\n]|,\s*(?:and\s+)?|\band\b|\bbut\b", t):
        seg = seg.strip()
        if not seg:
            continue
        factor = _find_factor(seg, available)
        if not factor:
            continue
        num = re.search(r"weight\w*\s+(?:of\s+|on\s+|for\s+)?(?:[a-z/\-\s]+?\s+)?(?:to|=|should be|of|at)\s+(\d+(?:\.\d+)?)\b", seg) \
            or re.search(r"(?:set|make)\s+[a-z/\-\s]+?\s+(?:weight\s+)?(?:to|=)\s+(\d+(?:\.\d+)?)\b", seg)
        if num:
            out[factor] = float(num.group(1))
        elif re.search(_IGNORE, seg):
            out[factor] = None
        elif re.search(r"\bweight|matter|emphas|count|import|trust|focus|rely", seg) or re.search(r"\b(double|halve|downweight|down-weight)\b", seg):
            if re.search(rf"\b{_DOWN}\b", seg) or re.search(r"\b(not trust|don'?t trust|less important|over-?weighted)\b", seg):
                out[factor] = round(current[factor] * 0.5, 3)
            elif re.search(rf"\b{_UP}\b", seg) or re.search(r"\b(more important|under-?weighted)\b", seg):
                out[factor] = round(current[factor] * 2, 3)
    return out
