"""
Pure, deterministic evaluation metrics for FinSight AI answers.

Every function here takes plain dicts (an `AnswerPayload` as saved by `/agent/chat`, or pieces of it)
and returns plain values, so the same code scores live runs, replayed fixtures and unit tests.
No function calls an LLM or the network.

Conventions
-----------
* A rate whose denominator is zero returns ``None`` ("not applicable"), never 0 or 1, so aggregates
  are not inflated by empty cases (e.g. citation coverage of a greeting with no claims).
* Number grounding is *lexical*: a number in a claim counts as grounded only if the same value
  (within the rounding precision the claim itself uses) appears in the output of an evidence item
  that the claim cites. Derived numbers (sums, differences, ratios the LLM computed itself) are
  therefore reported as ungrounded - the metric is a conservative lower bound.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

# --------------------------------------------------------------------------------------------
# Answer helpers
# --------------------------------------------------------------------------------------------


def iter_claims(answer: dict) -> Iterable[dict]:
    """Yield every claim dict of a FinalAnswer dict (sections -> claims)."""
    for sec in (answer or {}).get("sections") or []:
        for claim in sec.get("claims") or []:
            yield claim


def answer_text(answer: dict) -> str:
    """Flatten a FinalAnswer dict into one string (headline, verdict, section titles, claims, data gaps)."""
    a = answer or {}
    parts = [a.get("headline") or ""]
    if a.get("verdict"):
        parts.append(f"Verdict: {a['verdict']} {a.get('verdict_ticker') or ''}")
    for sec in a.get("sections") or []:
        parts.append(sec.get("title") or "")
        parts.extend(c.get("text") or "" for c in sec.get("claims") or [])
    parts.extend(a.get("data_gaps") or [])
    return "\n".join(p for p in parts if p)


def _rate(num: float, den: float) -> Optional[float]:
    return round(num / den, 4) if den else None


# --------------------------------------------------------------------------------------------
# Routing & tickers
# --------------------------------------------------------------------------------------------


def routing_correct(expected_intent: str, actual_intent: Optional[str]) -> bool:
    """True when the orchestrator's (post-processed) intent equals the expected intent."""
    return (actual_intent or "") == expected_intent


def normalize_ticker(t: str) -> str:
    """Upper-case and default to the NSE suffix, mirroring the orchestrator's post-processing."""
    t = (t or "").strip().upper()
    return t if t.endswith((".NS", ".BO")) or not t else f"{t}.NS"


def ticker_prf(expected: Sequence[str], actual: Sequence[str]) -> Dict[str, float]:
    """Set precision / recall / F1 of extracted tickers. Both empty -> all 1.0 (nothing to extract, nothing extracted)."""
    exp = {normalize_ticker(t) for t in expected or [] if t}
    act = {normalize_ticker(t) for t in actual or [] if t}
    if not exp and not act:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    tp = len(exp & act)
    p = tp / len(act) if act else 0.0
    r = tp / len(exp) if exp else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}


# --------------------------------------------------------------------------------------------
# Schema & citations
# --------------------------------------------------------------------------------------------


def schema_valid(answer: Any) -> tuple[bool, Optional[str]]:
    """Does the answer parse as the backend's `FinalAnswer` Pydantic model? Returns (ok, error)."""
    from backend.agent.schemas import FinalAnswer  # local import keeps this module light

    try:
        FinalAnswer.model_validate(answer)
        return True, None
    except Exception as e:  # pydantic.ValidationError or a non-dict
        return False, str(e).splitlines()[0][:200]


def citation_coverage(answer: dict) -> Optional[float]:
    """Share of claims that carry at least one citation. None when the answer has no claims."""
    claims = list(iter_claims(answer))
    return _rate(sum(1 for c in claims if c.get("citations")), len(claims))


def citation_validity(answer: dict, evidence: Sequence[dict]) -> Optional[float]:
    """Share of citation ids that exist in the evidence list. None when nothing is cited."""
    ids = {e.get("id") for e in evidence or []}
    cites = [x for c in iter_claims(answer) for x in c.get("citations") or []]
    return _rate(sum(1 for x in cites if x in ids), len(cites))


def invalid_citations(answer: dict, evidence: Sequence[dict]) -> List[str]:
    """Citation ids that do not exist in the evidence list (in order of appearance, de-duplicated)."""
    ids = {e.get("id") for e in evidence or []}
    out: List[str] = []
    for c in iter_claims(answer):
        for x in c.get("citations") or []:
            if x not in ids and x not in out:
                out.append(x)
    return out


# --------------------------------------------------------------------------------------------
# Number grounding
# --------------------------------------------------------------------------------------------

_NUM_RE = re.compile(
    r"(?P<sign>(?<![\w.\-])[-+−])?"        # sign only when not glued to a word/number (avoids dates like 2026-10-01)
    r"(?P<cur>₹|Rs\.?\s?|INR\s?)?"
    r"(?<![\w.])(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d|\.\d)"
    r"(?P<pct>\s?%|\s?per\s?cent)?",
    re.IGNORECASE,
)
# A number followed by one of these is a window/period label ("50-day", "3-month", "52-week", "RSI(14)"), not a data value.
_EXEMPT_AFTER = re.compile(r"^(?:\s?-?\s?(?:day|days|week|weeks|month|months|year|years|yr|yrs|quarter|session|sessions)\b"
                           r"|-\s*(?:and|or|to)\b|\)\s*\(|y\b|d\b|m\b|w\b)", re.IGNORECASE)
_EXEMPT_BEFORE = re.compile(r"(?:\bNIFTY\s?|\bSensex\s?|\bRSI\s?\(|\bQ|\bFY\s?'?|\bH|\bTop\s|\btop\s|\bEMA\s?|\bEMA-|\bMA\s?)$", re.IGNORECASE)

_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")


@dataclass
class NumberToken:
    """A number found in text."""
    text: str
    value: float
    decimals: int
    is_pct: bool
    currency: bool
    exempt: bool = False


def extract_numbers(text: str, apply_exemptions: bool = True) -> List[NumberToken]:
    """Find numbers in free text, tolerant of ₹, Indian/Western thousands separators, signs and %.

    With ``apply_exemptions`` numbers that are window/period labels ("50-day EMA", "3-month return",
    "RSI (14)", "NIFTY 50", "Q2", "FY25") are marked ``exempt`` and are not checked for grounding.
    """
    out: List[NumberToken] = []
    dates = [d.span() for d in _DATE_RE.finditer(text or "")]
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group("num")
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        sign = m.group("sign")
        if sign and sign in "-−":
            value = -value
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tok = NumberToken(text=m.group(0).strip(), value=value, decimals=decimals,
                          is_pct=bool(m.group("pct")), currency=bool(m.group("cur")))
        if apply_exemptions and any(a <= m.start("num") < b for a, b in dates):
            tok.exempt = True  # part of a calendar date such as 2026-10-01
        elif apply_exemptions and not tok.is_pct and not tok.currency:
            after = text[m.end():m.end() + 12]
            before = text[max(0, m.start() - 8):m.start()]
            if _EXEMPT_AFTER.match(after) or _EXEMPT_BEFORE.search(before):
                tok.exempt = True
        out.append(tok)
    return out


def evidence_numbers(output: Any) -> List[float]:
    """All numbers in a tool output: numeric leaves plus numbers written inside string leaves."""
    vals: List[float] = []

    def walk(v: Any) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            if math.isfinite(float(v)):
                vals.append(float(v))
        elif isinstance(v, str):
            vals.extend(t.value for t in extract_numbers(v, apply_exemptions=False))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    walk(output)
    return vals


def number_matches(tok: NumberToken, candidate: float) -> bool:
    """Is the claim number `tok` a faithful rendering of `candidate`?

    Tolerance is half a unit of the last digit the claim shows (so "26.53" matches 26.52708 and
    "₹1,533" matches 1533.4) plus a tiny relative epsilon. Signs are ignored ("33.8% below" for -33.78).
    A percentage also matches a fraction (54% <-> 0.54).
    """
    tol = 0.5 * 10 ** (-tok.decimals) + 1e-9 * max(1.0, abs(candidate))
    a = abs(tok.value)
    if abs(a - abs(candidate)) <= tol:
        return True
    if tok.is_pct and abs(candidate) <= 1.0 and abs(a - abs(candidate) * 100) <= tol:
        return True
    return False


def ground_claim(claim: dict, evidence_by_id: Dict[str, dict]) -> List[dict]:
    """Check each non-exempt number in a claim against the outputs of the evidence it cites.

    Returns one dict per checked number: ``{"text", "value", "grounded", "matched_in"}``.
    """
    pools = []
    for cid in claim.get("citations") or []:
        ev = evidence_by_id.get(cid)
        if ev is not None:
            pools.append((cid, evidence_numbers(ev.get("output"))))
    results = []
    for tok in extract_numbers(claim.get("text") or ""):
        if tok.exempt:
            continue
        hit = next((cid for cid, nums in pools if any(number_matches(tok, n) for n in nums)), None)
        results.append({"text": tok.text, "value": tok.value, "grounded": hit is not None, "matched_in": hit})
    return results


def number_grounding(answer: dict, evidence: Sequence[dict]) -> Dict[str, Any]:
    """Number grounding for a whole answer.

    Returns ``{"numbers": n, "grounded": g, "rate": g/n|None, "claims_with_numbers": k,
    "claims_fully_grounded": j, "claim_rate": j/k|None, "ungrounded": [{"claim", "number"}...]}``.
    """
    by_id = {e.get("id"): e for e in evidence or []}
    n = g = k = j = 0
    ungrounded = []
    for c in iter_claims(answer):
        res = ground_claim(c, by_id)
        if not res:
            continue
        k += 1
        n += len(res)
        ok = sum(1 for r in res if r["grounded"])
        g += ok
        j += ok == len(res)
        ungrounded += [{"claim": c.get("text"), "number": r["text"], "citations": c.get("citations") or []}
                       for r in res if not r["grounded"]]
    return {"numbers": n, "grounded": g, "rate": _rate(g, n), "claims_with_numbers": k,
            "claims_fully_grounded": j, "claim_rate": _rate(j, k), "ungrounded": ungrounded}


# --------------------------------------------------------------------------------------------
# Forbidden content
# --------------------------------------------------------------------------------------------

FOREIGN_TICKERS = re.compile(
    r"\b(AAPL|MSFT|AMZN|GOOGL?|TSLA|META|NVDA|NFLX|BRK\.?[AB]|JPM|NASDAQ|NYSE|S&P 500|Dow Jones)\b")
_SUFFIXED = re.compile(r"\b[A-Z][A-Z0-9&\-]{0,15}\.([A-Z]{1,3})\b")


def forbidden_content(text: str, must_not_include: Sequence[str] = ()) -> List[str]:
    """Problems in the answer text: foreign (non-NSE/BSE) securities, non-Indian exchange suffixes, and any
    case-specific forbidden phrase. Returns a list of offending strings (empty = pass)."""
    hits: List[str] = []
    hits += sorted({m.group(0) for m in FOREIGN_TICKERS.finditer(text or "")})
    hits += sorted({m.group(0) for m in _SUFFIXED.finditer(text or "") if m.group(1) not in ("NS", "BO")})
    low = (text or "").lower()
    hits += [p for p in must_not_include or [] if p.lower() in low]
    return hits


def missing_required(text: str, must_include: Sequence[str]) -> List[str]:
    """Case-specific required phrases (case-insensitive) that the answer does not contain.
    An entry with alternatives separated by '|' passes if any alternative is present."""
    low = (text or "").lower()
    return [p for p in must_include or [] if not any(alt.strip().lower() in low for alt in p.split("|"))]


# --------------------------------------------------------------------------------------------
# Verdict determinism (scorecard)
# --------------------------------------------------------------------------------------------


def _card_signature(cards: Sequence[dict]) -> List[tuple]:
    return sorted((c.get("ticker"), c.get("score"), c.get("verdict"), c.get("confidence")) for c in cards or [])


def verdict_determinism(evidence: Sequence[dict], tickers: Sequence[str], stored_scorecards: Optional[Sequence[dict]] = None,
                        answer: Optional[dict] = None, reruns: int = 3) -> Dict[str, Any]:
    """Re-run the deterministic scorecard (`backend.agent.scoring.build_scorecards`) on the recorded evidence.

    * ``deterministic``: identical output on every re-run (expected True by construction).
    * ``matches_stored``: re-computed cards equal the scorecards saved with the answer (None if none were saved,
      e.g. answers recorded before the scorecard existed).
    * ``answer_consistent``: the answer's BUY/SELL/HOLD equals the best re-computed card's verdict (None when
      the answer has no verdict or there is nothing to score).
    """
    from backend.agent.scoring import build_scorecards

    raw = [e for e in evidence or [] if e.get("tool") != "compute_signal_scorecard"]
    runs = [build_scorecards(json.loads(json.dumps(raw)), list(tickers or [])) for _ in range(max(1, reruns))]
    sigs = [json.dumps(r, sort_keys=True, default=str) for r in runs]
    cards = runs[0]
    stored = [c for c in stored_scorecards or []]
    if not stored:
        stored = [e["output"] for e in evidence or [] if e.get("tool") == "compute_signal_scorecard" and isinstance(e.get("output"), dict)]
    matches = (_card_signature(cards) == _card_signature(stored)) if stored else None
    consistent = None
    if answer and answer.get("verdict") and cards:
        best = max(cards, key=lambda c: c["score"])
        consistent = best["verdict"] == answer["verdict"]
    return {"n_cards": len(cards), "deterministic": len(set(sigs)) == 1, "matches_stored": matches,
            "answer_consistent": consistent, "recomputed": [{"ticker": c["ticker"], "score": c["score"], "verdict": c["verdict"]} for c in cards]}


# --------------------------------------------------------------------------------------------
# Latency, tokens & aggregation
# --------------------------------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    """Linear-interpolated percentile (q in [0, 100]) of the non-None values; None if empty."""
    xs = sorted(float(v) for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return round(xs[0], 3)
    pos = (len(xs) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo), 3)


def usage_from_payload(payload: dict) -> Dict[str, Optional[float]]:
    """Token / cost figures if the payload recorded them (keys `usage` or `llm_usage`); otherwise all None."""
    u = (payload or {}).get("usage") or (payload or {}).get("llm_usage") or {}
    pick = lambda *ks: next((u[k] for k in ks if isinstance(u.get(k), (int, float))), None)  # noqa: E731
    return {"prompt_tokens": pick("prompt_tokens", "input_tokens"), "completion_tokens": pick("completion_tokens", "output_tokens"),
            "total_tokens": pick("total_tokens"), "cost_usd": pick("cost_usd", "cost")}


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    """Mean of the non-None values (bools count as 0/1); None if there are none."""
    xs = [float(v) for v in values if v is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def as_dict(tok: NumberToken) -> dict:
    """Serialise a NumberToken."""
    return asdict(tok)


def perturb_numbers(answer: dict, factor: float = 1.1) -> dict:
    """Negative control: a deep copy of the answer with every checkable claim number scaled by `factor`
    (rendered with the same decimals and forced to change). Grounding of the perturbed answer should be ~0;
    whatever stays "grounded" is the metric's false-positive rate."""
    import copy

    out = copy.deepcopy(answer)
    for c in iter_claims(out):
        text = c.get("text") or ""
        for tok in sorted((t for t in extract_numbers(text) if not t.exempt), key=lambda t: -len(t.text)):
            old = tok.text.lstrip("-+−").replace("₹", "").replace("Rs.", "").replace("Rs", "").replace("INR", "")
            old = re.sub(r"\s?(%|per\s?cent)$", "", old.strip(), flags=re.IGNORECASE).strip()
            new_v = abs(tok.value) * factor
            new = f"{new_v:.{tok.decimals}f}"
            if new == f"{abs(tok.value):.{tok.decimals}f}":
                new = f"{new_v + 10 ** -tok.decimals:.{tok.decimals}f}"
            text = text.replace(old, new, 1)
        c["text"] = text
    return out
