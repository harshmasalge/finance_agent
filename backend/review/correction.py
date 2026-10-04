"""
Correction Agent: turns an analyst's natural-language correction into a revised answer.

Order of operations (cheapest and most deterministic first):
1. Weighting corrections ("ignore the XGBoost signal", "weight valuation higher") are parsed
   with rules and applied to the scorecard deterministically - no LLM call, same input gives
   the same verdict.
2. Checkable fact corrections ("RSI should be 45") are compared with the numeric tool outputs.
   If the evidence disagrees, the correction is rejected with a pushback that cites the
   evidence id; if the evidence agrees and a claim misstates it, the claim is fixed in place.
3. Everything else goes to an injected structured LLM that returns a `CorrectionResult`.
   Its output is sanitised: the answer type is kept, citations must exist, and the verdict
   is always re-derived from the (possibly re-weighted) scorecard, never from the LLM.
"""
import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.agent.evidence import evidence_digest
from backend.agent.schemas import FinalAnswer
from backend.review.reweight import parse_weighting, reweight_card

Category = Literal["fact", "judgement", "weighting", "format"]


class ChangeLogEntry(BaseModel):
    path: str = Field(description="Where the change is, e.g. 'headline', 'sections[1].claims[0].text', 'verdict'.")
    before: Optional[str] = Field(default=None, description="Previous value (null when added).")
    after: Optional[str] = Field(default=None, description="New value (null when removed).")
    reason: str = Field(description="Why this change was made, citing evidence ids where relevant.")


class CorrectionResult(BaseModel):
    category: Category = Field(description="fact: a number/fact is wrong; judgement: interpretation or emphasis; "
                                           "weighting: how much a scorecard factor should count; format: wording/structure.")
    accepted: bool = Field(description="False if the correction contradicts the cited evidence.")
    pushback: Optional[str] = Field(default=None, description="When accepted=false: why, citing the evidence id(s) and values.")
    revised_answer: FinalAnswer = Field(description="The full corrected answer (unchanged copy when accepted=false).")
    change_log: List[ChangeLogEntry] = Field(default_factory=list, description="One entry per changed field.")
    scorecard_overrides: Dict[str, Optional[float]] = Field(
        default_factory=dict, description="Scorecard factor name -> new weight (null = ignore). Only for weighting corrections.")


@dataclass
class CorrectionOutcome:
    """Everything the review service needs to store a correction."""
    result: CorrectionResult
    answer: dict
    scorecards: List[dict]
    evidence: List[dict]
    agent_response: str
    source: str  # rules | evidence_check | llm
    weight_changes: List[dict] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.result.accepted and bool(self.result.change_log)


class LLMUnavailable(RuntimeError):
    """Raised when a correction needs the LLM and the LLM call fails."""


# ---------------------------------------------------------------- helpers
def _fmt(v: Any) -> Optional[str]:
    if v is None:
        return None
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def diff_answers(before: dict, after: dict, reason: str) -> List[ChangeLogEntry]:
    """Field/claim level diff between two FinalAnswer dicts."""
    log: List[ChangeLogEntry] = []
    for key in ("headline", "verdict", "verdict_ticker", "confidence"):
        if before.get(key) != after.get(key):
            log.append(ChangeLogEntry(path=key, before=_fmt(before.get(key)), after=_fmt(after.get(key)), reason=reason))
    bs, as_ = before.get("sections") or [], after.get("sections") or []
    for i in range(max(len(bs), len(as_))):
        b = bs[i] if i < len(bs) else None
        a = as_[i] if i < len(as_) else None
        if b and a and b.get("title") != a.get("title"):
            log.append(ChangeLogEntry(path=f"sections[{i}].title", before=b.get("title"), after=a.get("title"), reason=reason))
        bc, ac = (b or {}).get("claims") or [], (a or {}).get("claims") or []
        for j in range(max(len(bc), len(ac))):
            x = bc[j] if j < len(bc) else None
            y = ac[j] if j < len(ac) else None
            if (x or {}).get("text") != (y or {}).get("text") or (x or {}).get("citations") != (y or {}).get("citations"):
                log.append(ChangeLogEntry(path=f"sections[{i}].claims[{j}]", before=(x or {}).get("text"),
                                          after=(y or {}).get("text"), reason=reason))
    if (before.get("data_gaps") or []) != (after.get("data_gaps") or []):
        log.append(ChangeLogEntry(path="data_gaps", before=_fmt(before.get("data_gaps")), after=_fmt(after.get("data_gaps")), reason=reason))
    return log


def _apply_verdict(answer: dict, scorecards: List[dict]) -> None:
    """The verdict always comes from the scorecard (mirrors synthesis_node)."""
    if answer.get("answer_type") not in ("stock_analysis", "comparison"):
        answer["verdict"] = answer["verdict_ticker"] = answer["confidence"] = None
    elif scorecards:
        best = max(scorecards, key=lambda c: c["score"])
        answer["verdict"], answer["verdict_ticker"], answer["confidence"] = best["verdict"], best["ticker"], best["confidence"]


def _num_variants(v: float) -> List[Tuple[str, str]]:
    return [(f"{v:+.1f}", "+"), (f"{v:.1f}", ""), (f"{v:+.0f}", "+0"), (f"{v:.0f}", "0")]


def apply_weighting(answer: dict, evidence: List[dict], scorecards: List[dict], overrides: Dict[str, Optional[float]],
                    reason: str) -> Tuple[dict, List[dict], List[dict], List[ChangeLogEntry], List[dict]]:
    """Re-weight every scorecard that has the overridden factors and propagate the result to the
    verdict, the scorecard evidence item, claims that quote the old score/verdict, and an
    'Analyst adjustments' section. Returns (answer, evidence, scorecards, change_log, weight_changes)."""
    answer, evidence = copy.deepcopy(answer), copy.deepcopy(evidence)
    new_cards, log, all_changes, notes = [], [], [], []
    for card in scorecards:
        new, changes = reweight_card(card, overrides)
        new_cards.append(new)
        if not changes:
            continue
        tk, eid = card["ticker"], card.get("evidence_id")
        for ch in changes:
            all_changes.append({**ch, "ticker": tk})
            log.append(ChangeLogEntry(path=f"scorecards[{tk}].factors.{ch['factor']}.weight", before=_fmt(ch["before"]),
                                      after=_fmt(ch["after"]), reason=reason))
        if new["score"] != card["score"]:
            log.append(ChangeLogEntry(path=f"scorecards[{tk}].score", before=_fmt(card["score"]), after=_fmt(new["score"]),
                                      reason="Recomputed from the factor scores with the new weights."))
        if new["verdict"] != card["verdict"]:
            log.append(ChangeLogEntry(path=f"scorecards[{tk}].verdict", before=card["verdict"], after=new["verdict"],
                                      reason=f"Score {new['score']:+} crosses the {card.get('thresholds', {})} thresholds."))
        for e in evidence:
            if e.get("id") == eid or (e.get("tool") == "compute_signal_scorecard" and (e.get("output") or {}).get("ticker") == tk):
                e["output"] = new
        # Patch text that quotes the old score/verdict for this card.
        def patch(text: str) -> str:
            for (old_s, style) in _num_variants(card["score"]):
                new_s = {"+": f"{new['score']:+.1f}", "": f"{new['score']:.1f}", "+0": f"{new['score']:+.0f}", "0": f"{new['score']:.0f}"}[style]
                text = re.sub(rf"(?<![\d.]){re.escape(old_s)}(?![\d])", new_s, text)
            if new["verdict"] != card["verdict"]:
                text = re.sub(rf"\b{card['verdict']}\b", new["verdict"], text)
            return text
        if eid:
            for i, sec in enumerate(answer.get("sections") or []):
                for j, c in enumerate(sec.get("claims") or []):
                    if eid in (c.get("citations") or []):
                        t2 = patch(c["text"])
                        if t2 != c["text"]:
                            log.append(ChangeLogEntry(path=f"sections[{i}].claims[{j}]", before=c["text"], after=t2,
                                                      reason="Updated to the re-weighted scorecard."))
                            c["text"] = t2
        if new["verdict"] != card["verdict"] and tk == answer.get("verdict_ticker"):
            h2 = re.sub(rf"\b{card['verdict']}\b", new["verdict"], answer.get("headline") or "")
            if h2 != answer.get("headline"):
                log.append(ChangeLogEntry(path="headline", before=answer["headline"], after=h2, reason="Updated to the re-weighted verdict."))
                answer["headline"] = h2
        what = "; ".join(f"{c['label']} weight {c['before']:g} → {c['after']:g}" + (" (ignored)" if c["after"] == 0 else "") for c in changes)
        move = f"verdict {card['verdict']} → {new['verdict']}" if new["verdict"] != card["verdict"] else f"verdict stays {new['verdict']}"
        notes.append({"text": f"Analyst override for {tk.split('.')[0]}: {what}; score {card['score']:+.1f} → {new['score']:+.1f}, {move}.",
                      "citations": [eid] if eid else []})

    if notes:
        before_verdict = {k: answer.get(k) for k in ("verdict", "verdict_ticker", "confidence")}
        _apply_verdict(answer, new_cards)
        for k, v in before_verdict.items():
            if answer.get(k) != v:
                log.append(ChangeLogEntry(path=k, before=_fmt(v), after=_fmt(answer.get(k)), reason="Re-derived from the re-weighted scorecard."))
        secs = answer.setdefault("sections", [])
        idx = next((i for i, s in enumerate(secs) if s.get("title") == "Analyst adjustments"), None)
        if idx is None:
            secs.insert(0, {"title": "Analyst adjustments", "claims": []})
            idx = 0
            for e in log:  # earlier paths referred to the pre-insert section indices
                e.path = re.sub(r"^sections\[(\d+)\]", lambda m: f"sections[{int(m.group(1)) + 1}]", e.path)
        for n in notes:
            secs[idx]["claims"].append(n)
            log.append(ChangeLogEntry(path=f"sections[{idx}].claims[{len(secs[idx]['claims']) - 1}]", before=None, after=n["text"], reason=reason))
    return answer, evidence, new_cards, log, all_changes


# ---------------------------------------------------------------- evidence check
# phrase -> (output key, scale) ; scale 100 means the evidence stores a fraction shown as a percent.
METRICS: List[Tuple[str, str, float]] = [
    ("forward p/e", "pe_forward", 1), ("forward pe", "pe_forward", 1),
    ("trailing p/e", "pe_trailing", 1), ("p/e", "pe_trailing", 1), ("pe ratio", "pe_trailing", 1),
    ("price to book", "price_to_book", 1), ("price-to-book", "price_to_book", 1), ("p/b", "price_to_book", 1),
    ("rsi", "rsi_14", 1), ("revenue growth", "revenue_growth_pct", 1), ("earnings growth", "earnings_growth_pct", 1),
    ("profit margin", "profit_margin_pct", 1), ("roe", "roe_pct", 1), ("return on equity", "roe_pct", 1),
    ("dividend yield", "dividend_yield_pct", 1), ("debt to equity", "debt_to_equity", 1), ("debt-to-equity", "debt_to_equity", 1),
    ("3-month return", "return_3m_pct", 1), ("3 month return", "return_3m_pct", 1), ("1-month return", "return_1m_pct", 1),
    ("200-day ema", "ema_200", 1), ("ema 200", "ema_200", 1), ("50-day ema", "ema_50", 1), ("ema 50", "ema_50", 1),
    ("20-day ema", "ema_20", 1), ("ema 20", "ema_20", 1), ("52-week high", "high_52w", 1), ("52-week low", "low_52w", 1),
    ("last close", "last_close", 1), ("closing price", "last_close", 1), ("market cap", "market_cap_cr", 1),
    ("holdout accuracy", "holdout_accuracy", 100), ("eps", "eps_trailing", 1),
]
_CLAIM_NUM = re.compile(r"(?:should be|is actually|is really|must be|=|is)\s*₹?\s*(-?\d[\d,]*(?:\.\d+)?)\s*%?")


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.5, 0.02 * abs(b))


def check_against_evidence(text: str, evidence: List[dict], tickers: List[str]) -> Optional[dict]:
    """Find `<metric> should be <number>` in `text` and compare it with the tool outputs.

    Returns None if nothing checkable was found, else
    {"metric", "key", "claimed", "value", "evidence_id", "tool", "as_of", "matches": bool}.
    """
    t = text.lower()
    m = _CLAIM_NUM.search(t)
    if not m:
        return None
    head = t[:m.start()]
    found = None
    for phrase, key, scale in METRICS:
        pos = head.rfind(phrase)
        if pos < 0 or not re.match(rf"{re.escape(phrase)}(?![a-z])", head[pos:]) or (pos > 0 and head[pos - 1].isalpha()):
            continue
        rank = (pos + len(phrase), len(phrase))
        if found is None or rank > found[0]:
            found = (rank, phrase, key, scale)
    if not found:
        return None
    _, phrase, key, scale = found
    claimed = float(m.group(1).replace(",", ""))
    for e in evidence:
        out = e.get("output") if isinstance(e.get("output"), dict) else {}
        v = out.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if tickers and out.get("ticker") and out["ticker"] not in tickers:
            continue
        matches = _close(claimed, v) or (scale != 1 and _close(claimed, v * scale))
        return {"metric": phrase, "key": key, "claimed": claimed, "value": v, "evidence_id": e["id"], "tool": e["tool"],
                "as_of": out.get("as_of"), "ticker": out.get("ticker"), "scale": scale, "matches": matches}
    return None


def _fix_claims_from_evidence(answer: dict, chk: dict) -> Tuple[dict, List[ChangeLogEntry]]:
    """Rewrite numbers that misstate `chk['value']` in claims citing its evidence id and naming the metric."""
    answer = copy.deepcopy(answer)
    log = []
    shown = chk["value"] * chk["scale"]
    new_s = f"{shown:,.2f}".rstrip("0").rstrip(".")
    for i, sec in enumerate(answer.get("sections") or []):
        for j, c in enumerate(sec.get("claims") or []):
            if chk["evidence_id"] not in (c.get("citations") or []):
                continue
            low = c["text"].lower()
            pos = low.find(chk["metric"])
            if pos < 0:
                continue
            m = re.compile(r"-?\d[\d,]*(?:\.\d+)?").search(c["text"], pos + len(chk["metric"]))
            if not m or m.start() - pos > 60:
                continue
            old = float(m.group(0).replace(",", ""))
            if _close(old, shown):
                continue
            t2 = c["text"][:m.start()] + new_s + c["text"][m.end():]
            log.append(ChangeLogEntry(path=f"sections[{i}].claims[{j}]", before=c["text"], after=t2,
                                      reason=f"{chk['evidence_id']} ({chk['tool']}) reports {chk['key']} = {chk['value']}."))
            c["text"] = t2
    return answer, log


# ---------------------------------------------------------------- LLM prompt
SYSTEM = """You are the Correction Agent of FinSight AI. A human equity analyst (subject-matter expert) is reviewing an
answer produced by our research agents and has written a correction in plain English. Revise the answer.

Rules:
1. Classify the correction: fact | judgement | weighting | format.
2. If the correction contradicts the cited tool evidence (a number or fact the evidence states differently), do NOT apply it:
   set accepted=false, return the answer unchanged, and write a short, polite pushback that names the evidence id(s)
   and the exact values, e.g. "R1 (technical indicators, as of 2026-10-01) reports RSI 18.2, not 45.".
3. Otherwise set accepted=true and change ONLY what the correction requires. Keep every other claim verbatim.
   Every claim stating a fact must keep valid citations (ids from the evidence list only).
4. Never set the BUY/SELL/HOLD verdict yourself; it is computed by the scorecard. If the analyst wants a factor to count
   more, less or not at all, put it in scorecard_overrides as {factor_name: new_weight or null to ignore}.
5. change_log: one entry per changed field with path (e.g. "sections[2].claims[1]"), before, after and a reason.
"""


def build_messages(answer: dict, evidence: List[dict], scorecards: List[dict], text: str, target: Optional[str]) -> list:
    cards = "\n".join(f"{c['ticker']}: score {c['score']:+} -> {c['verdict']}; factors: " +
                      ", ".join(f"{f['name']} (score {f['score']:+.2f}, weight {f['weight']})" for f in c.get("factors", []))
                      for c in scorecards) or "(none)"
    human = (f"=== CURRENT ANSWER ===\n{json.dumps(answer, indent=1, ensure_ascii=False)}\n\n"
             f"=== SCORECARDS ===\n{cards}\n\n=== EVIDENCE ===\n{evidence_digest(evidence, max_chars=1200)}\n\n"
             f"=== ANALYST CORRECTION ===\n" + (f"(about: {target})\n" if target else "") + text)
    return [SystemMessage(SYSTEM), HumanMessage(human)]


def default_llm():
    """The production model: structured output into CorrectionResult (imported lazily, needs an API key)."""
    from backend.agent.utils import get_structured_llm
    return get_structured_llm(CorrectionResult, temperature=0)


# ---------------------------------------------------------------- agent
class CorrectionAgent:
    """Apply one analyst correction. `llm` is anything with `.invoke(messages) -> CorrectionResult | dict`,
    or a zero-arg factory returning one (called only when the LLM is actually needed)."""

    def __init__(self, llm: Any = None, llm_factory: Optional[Callable[[], Any]] = None):
        self._llm = llm
        self._factory = llm_factory or default_llm

    @property
    def llm(self):
        if self._llm is None:
            self._llm = self._factory()
        return self._llm

    def run(self, answer: dict, evidence: List[dict], scorecards: List[dict], text: str,
            target: Optional[str] = None, tickers: Optional[List[str]] = None) -> CorrectionOutcome:
        """Return the outcome of applying `text` to the current answer (never mutates the inputs)."""
        answer, evidence, scorecards = copy.deepcopy(answer), copy.deepcopy(evidence or []), copy.deepcopy(scorecards or [])
        reason = f"Analyst: \"{text.strip()}\""

        # 1. Weighting rules
        overrides = parse_weighting(text, scorecards)
        if overrides:
            new_answer, new_ev, new_cards, log, changes = apply_weighting(answer, evidence, scorecards, overrides, reason)
            res = CorrectionResult(category="weighting", accepted=True, revised_answer=FinalAnswer(**new_answer),
                                   change_log=log, scorecard_overrides=overrides)
            return CorrectionOutcome(res, new_answer, new_cards, new_ev, self._explain(res, changes, new_cards, scorecards), "rules", changes)

        # 2. Evidence check for "<metric> should be <n>"
        chk = check_against_evidence(text, evidence, tickers or [])
        if chk and not chk["matches"]:
            shown = chk["value"] * chk["scale"]
            when = f", as of {chk['as_of']}" if chk.get("as_of") else ""
            push = (f"I kept the answer unchanged: {chk['evidence_id']} ({chk['tool']}{when}) reports {chk['key']} = {shown:g}"
                    f"{' for ' + chk['ticker'] if chk.get('ticker') else ''}, not {chk['claimed']:g}. "
                    "If you have a newer source, tell me which and I will note it as an analyst override.")
            res = CorrectionResult(category="fact", accepted=False, pushback=push, revised_answer=FinalAnswer(**answer))
            return CorrectionOutcome(res, answer, scorecards, evidence, push, "evidence_check")
        if chk and chk["matches"]:
            fixed, log = _fix_claims_from_evidence(answer, chk)
            res = CorrectionResult(category="fact", accepted=True, revised_answer=FinalAnswer(**fixed), change_log=log)
            msg = self._explain(res, [], scorecards, scorecards) if log else (
                f"Agreed - {chk['evidence_id']} ({chk['tool']}) reports {chk['key']} = {chk['value']:g}, and no statement in the answer contradicts it, so nothing changed.")
            return CorrectionOutcome(res, fixed, scorecards, evidence, msg, "evidence_check")

        # 3. LLM
        try:
            raw = self.llm.invoke(build_messages(answer, evidence, scorecards, text, target))
        except Exception as e:  # no credits / network / parse failure
            raise LLMUnavailable(f"The Correction Agent's language model is unavailable ({type(e).__name__}: {str(e)[:160]}). "
                                 "Weighting corrections (e.g. 'ignore the XGBoost signal') and evidence-checkable numbers still work.") from e
        res = raw if isinstance(raw, CorrectionResult) else CorrectionResult.model_validate(raw)
        return self._finish_llm(res, answer, evidence, scorecards, reason)

    def _finish_llm(self, res: CorrectionResult, answer: dict, evidence: List[dict], scorecards: List[dict], reason: str) -> CorrectionOutcome:
        if not res.accepted:
            if not res.pushback:
                res.pushback = "The correction conflicts with the cited evidence, so the answer was kept unchanged."
            res.revised_answer, res.change_log, res.scorecard_overrides = FinalAnswer(**answer), [], {}
            return CorrectionOutcome(res, answer, scorecards, evidence, res.pushback, "llm")

        revised = res.revised_answer.model_dump()
        revised["answer_type"] = answer.get("answer_type")
        valid = {e["id"] for e in evidence}
        for sec in revised.get("sections") or []:
            for c in sec.get("claims") or []:
                c["citations"] = [x for x in c.get("citations") or [] if x in valid]
        _apply_verdict(revised, scorecards)
        llm_log = {e.path: e for e in res.change_log}
        log = [ChangeLogEntry(path=d.path, before=d.before, after=d.after, reason=llm_log[d.path].reason if d.path in llm_log else reason)
               for d in diff_answers(answer, revised, reason)]
        cards, changes = scorecards, []
        if res.scorecard_overrides:
            revised, evidence, cards, wlog, changes = apply_weighting(revised, evidence, scorecards, res.scorecard_overrides, reason)
            log += wlog
        res.revised_answer, res.change_log = FinalAnswer(**revised), log
        if changes and res.category != "weighting":
            res.category = "weighting" if not diff_answers(answer, revised, reason) else res.category
        return CorrectionOutcome(res, revised, cards, evidence, self._explain(res, changes, cards, scorecards), "llm", changes)

    @staticmethod
    def _explain(res: CorrectionResult, changes: List[dict], new_cards: List[dict], old_cards: List[dict]) -> str:
        """Short plain-English explanation of what was changed, shown in the review chat."""
        if not res.change_log:
            return "I checked the answer against your note and nothing needed to change."
        parts = []
        old = {c["ticker"]: c for c in old_cards}
        for c in new_cards:
            o = old.get(c["ticker"])
            if o and (o["score"] != c["score"] or o["verdict"] != c["verdict"]):
                ch = [x for x in changes if x.get("ticker") == c["ticker"]]
                what = ", ".join(f"{x['label']} weight {x['before']:g}→{x['after']:g}" for x in ch)
                parts.append(f"Re-weighted the {c['ticker'].split('.')[0]} scorecard ({what}): score {o['score']:+.1f} → {c['score']:+.1f}, "
                             + (f"verdict {o['verdict']} → {c['verdict']}." if o["verdict"] != c["verdict"] else f"verdict stays {c['verdict']}."))
        text_changes = [e for e in res.change_log if (e.path.startswith("sections") or e.path == "headline") and e.before is not None]
        added = [e for e in res.change_log if e.path.startswith("sections") and e.before is None and e.after]
        if text_changes:
            reasons = [r for r in dict.fromkeys(e.reason for e in text_changes) if not r.startswith("Analyst:")]
            parts.append(f"Updated {len(text_changes)} statement{'s' if len(text_changes) != 1 else ''}"
                         + (f" ({'; '.join(reasons)[:300].rstrip('.')})." if reasons else "."))
        if added:
            parts.append(f"Added {len(added)} note{'s' if len(added) != 1 else ''} explaining the change.")
        return " ".join(parts) or f"Applied {len(res.change_log)} change(s)."
