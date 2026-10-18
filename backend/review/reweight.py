"""Deterministic scorecard re-weighting for analyst weighting corrections.

Recomputes a stored scorecard from its own factors with weight overrides, using
`backend.agent.scoring.summarize` (the scorecard's own formula), without re-running any tools.
"""
import copy
import re
from typing import Dict, List, Optional, Tuple

from backend.agent.scoring import summarize

Overrides = Dict[str, Optional[float]]

# Phrases an analyst may use for each factor, longest first so "prophet trend" wins over "trend".
FACTOR_ALIASES: Dict[str, List[str]] = {
    "prophet": ["prophet trend", "prophet"],
    "trend": ["long-term trend", "long term trend", "ema trend", "trend"],
    "momentum": ["short-term momentum", "momentum", "macd"],
    "rsi": ["rsi"],
    "returns": ["3-month return", "3 month return", "three-month return", "past returns", "returns"],
    # XGBoost and Prophet no longer vote (removed 2026-10-18); kept so corrections on older answers still parse.
    "xgboost": ["xgboost", "xgb", "ml model", "machine learning model", "ml signal"],
    "valuation": ["valuation", "peg", "p/e", "pe ratio"],
    "growth": ["revenue growth", "growth"],
    "sentiment": ["news sentiment", "sentiment", "news"],
}

_IGNORE = r"(ignore|ignoring|drop|exclude|remove|disregard|don'?t (?:use|count|consider)|do not (?:use|count|consider)|zero(?:\s+out)?|no weight (?:on|for|to)|(?:should|must|does|do)\s*(?:n'?t|not)\s+(?:count|matter|be used|be counted|be considered))"
_UP = r"(higher|more|up|increase|double|heavier|heavily|more heavily|stronger)"
_DOWN = r"(lower|less|down|decrease|reduce|halve|lighter|lightly|downweight|down-weight|weaker)"


def compute(card: dict) -> dict:
    """Recompute score, verdict, confidence and coverage of `card` from its factors (in place copy).

    Uses `backend.agent.scoring.summarize`, the same function the scorecard itself uses. A card that had
    no verdict because its inputs were invalid (INSUFFICIENT_DATA) stays that way: re-weighting cannot add data.
    """
    card = copy.deepcopy(card)
    card.update(summarize(card.get("factors") or [], card.get("thresholds"), card.get("insufficient_reason")))
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
