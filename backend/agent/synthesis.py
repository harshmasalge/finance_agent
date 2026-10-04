"""Synthesis (final answer) and Validator (checker) nodes."""
import json
import re
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.evidence import evidence_digest
from backend.agent.schemas import FinalAnswer, ValidationVerdict
from backend.agent.scoring import BUY_THRESHOLD, SELL_THRESHOLD, build_scorecards
from backend.agent.state import AgentState
from backend.agent.utils import get_llm, get_structured_llm

MAX_ATTEMPTS = 2  # first answer + one revision

ANSWER_FORMATS = {
    "research": ("stock_analysis",
                 "The verdict is FIXED by the signal scorecard (see SCORECARD). Explain why the factors lead to it - lead with the "
                 "strongest factors for and against. Sections: 'Why this verdict', 'Price & trend', 'Fundamentals', 'Model signals', "
                 "'News & sentiment', 'Fit with your portfolio'."),
    "comparison": ("comparison",
                   "Compare the stocks side by side using their scorecards; the stock with the higher score is preferred and its "
                   "scorecard verdict is the verdict. Use one section per stock plus a 'Head to head' section."),
    "portfolio": ("portfolio_health",
                  "Do NOT give a BUY/SELL/HOLD verdict. Sections: 'Overview', 'Allocation & concentration', 'Performance', "
                  "'Suggested actions'. Suggested actions must follow from the cited data."),
    "ideas": ("ideas",
              "No verdict. Sections: 'Candidates' (one claim per candidate stock with its key numbers), "
              "'How they fit your portfolio', 'Caveats'. Only suggest stocks that appear in the screener evidence."),
    "sentiment": ("sentiment", "No verdict. Sections: 'Recent news', 'Sentiment read'."),
}

SYNTHESIS_RULES = """You are the Synthesis Agent of FinSight AI, an assistant for Indian equities (NSE/BSE) on a paper-trading account.
Write the final answer from the agent reports and the raw tool evidence below.

Hard rules:
1. Every claim that states a fact or number MUST cite the evidence ids (e.g. "R2", "P1") that support it. Use only ids that exist below.
2. Use ONLY the evidence. No outside knowledge, no invented numbers, news or events.
3. Only discuss Indian NSE/BSE stocks that appear in the evidence. Never mention US or other foreign stocks.
4. If data is missing (available=false), say so in data_gaps and lower confidence. Missing sentiment is "unknown", never "stable".
5. The verdict must be consistent with the evidence; mention conflicting signals.
6. Keep claims short (one sentence each), 2-4 claims per section. Use ₹ for prices."""


def _general_answer(state: AgentState) -> dict:
    llm = get_llm(temperature=0.3)
    if state.get("intent") == "clarify":
        q = state.get("clarification_question") or "Which stock would you like me to look at? (e.g. TCS, Infosys, Reliance)"
        return FinalAnswer(answer_type="general", headline=q).model_dump()
    reply = llm.invoke([
        SystemMessage("You are FinSight AI, a friendly assistant for Indian stock research and a paper-trading portfolio. "
                      "Answer briefly. You can: analyse NSE stocks, compare stocks, check portfolio health, and suggest ideas. "
                      "Do not state live market numbers - offer to analyse instead."),
        *state["messages"][-6:],
    ])
    return FinalAnswer(answer_type="general", headline=reply.content).model_dump()


def synthesis_node(state: AgentState) -> dict:
    intent = state.get("intent")
    attempts = int(state.get("attempts") or 0) + 1
    if intent not in ANSWER_FORMATS:
        return {"final_answer": _general_answer(state), "attempts": attempts}

    answer_type, fmt = ANSWER_FORMATS[intent]
    update: dict = {}
    scorecards = state.get("scorecards")
    if scorecards is None and intent in ("research", "comparison"):
        evidence = state.get("evidence") or []
        scorecards = build_scorecards(evidence, state.get("target_tickers") or [])
        new_ev = []
        for i, card in enumerate(scorecards, 1):
            card["evidence_id"] = f"C{i}"
            new_ev.append({"id": f"C{i}", "agent": "Scoring Engine", "tool": "compute_signal_scorecard",
                           "input": {"ticker": card["ticker"]}, "output": card, "created_at": evidence[-1]["created_at"] if evidence else None})
        update = {"scorecards": scorecards, "evidence": new_ev}
        state = {**state, "evidence": (state.get("evidence") or []) + new_ev}
    scorecards = scorecards or []
    reports = {k: state.get(k) for k in ("research_output", "sentiment_output", "risk_output") if state.get(k)}
    feedback = state.get("validation_feedback") or []
    revision = ("\n\nYOUR PREVIOUS DRAFT FAILED REVIEW. Fix these issues:\n- " + "\n- ".join(feedback)) if feedback else ""

    tickers = state.get("target_tickers") or []
    if answer_type == "comparison" and tickers:
        fmt += f" You MUST include one section titled with each stock: {', '.join(t.split('.')[0] for t in tickers)}, then 'Head to head'."
    score_txt = ""
    if scorecards:
        score_txt = ("\n\n=== SCORECARD (deterministic; cite its evidence id, e.g. C1) ===\n"
                     f"Rules: score >= {BUY_THRESHOLD} -> BUY, <= {SELL_THRESHOLD} -> SELL, otherwise HOLD.\n" +
                     "\n".join(f"{c['ticker']} [{c['evidence_id']}]: score {c['score']:+} -> {c['verdict']} (confidence {c['confidence']:.0%}); factors: " +
                               "; ".join(f"{f['label']} {f['score']:+.2f} ({f['reason']})" for f in c["factors"]) for c in scorecards))
    system = (f"{SYNTHESIS_RULES}\n\nAnswer type: {answer_type}. {fmt}{score_txt}\n\n"
              f"=== AGENT REPORTS ===\n{json.dumps(reports, indent=1, default=str)}\n\n"
              f"=== RAW EVIDENCE ===\n{evidence_digest(state.get('evidence') or [])}{revision}")
    llm = get_structured_llm(FinalAnswer, temperature=0.1)
    answer: FinalAnswer = llm.invoke([SystemMessage(system), *state["messages"][-4:]])
    answer.answer_type = answer_type
    if not answer.data_gaps:  # carry over gaps the agents reported
        seen = []
        for r in reports.values():
            for g in (r or {}).get("data_gaps", []):
                if g not in seen:
                    seen.append(g)
        answer.data_gaps = seen[:5]
    if answer_type not in ("stock_analysis", "comparison"):
        answer.verdict, answer.verdict_ticker, answer.confidence = None, None, None
    elif scorecards:
        # The verdict always comes from the scorecard, never from the LLM.
        best = max(scorecards, key=lambda c: c["score"])
        answer.verdict, answer.verdict_ticker, answer.confidence = best["verdict"], best["ticker"], best["confidence"]
    return {**update, "final_answer": answer.model_dump(), "attempts": attempts}


FOREIGN_TICKER = re.compile(r"\b(AAPL|MSFT|AMZN|GOOGL?|TSLA|META|NVDA|NFLX|NASDAQ|NYSE|S&P 500)\b")


def _deterministic_checks(answer: dict, evidence_ids: set, tickers: List[str]) -> List[str]:
    issues = []
    sections = answer.get("sections", [])
    if len(sections) < 2:
        issues.append("The answer needs at least two sections covering the requested format.")
    if answer.get("answer_type") == "comparison":
        titles = " ".join(sec.get("title", "") for sec in sections).upper()
        for t in tickers:
            if t.split(".")[0].upper() not in titles:
                issues.append(f"Comparison is missing a section for {t.split('.')[0]}.")
    for sec in answer.get("sections", []):
        for c in sec.get("claims", []):
            if not c.get("citations"):
                issues.append(f"Claim has no citation: \"{c['text'][:90]}\"")
            bad = [x for x in c.get("citations", []) if x not in evidence_ids]
            if bad:
                issues.append(f"Claim cites non-existent evidence {bad}: \"{c['text'][:90]}\"")
    text = json.dumps(answer)
    if FOREIGN_TICKER.search(text):
        issues.append(f"Mentions a non-Indian security ({FOREIGN_TICKER.search(text).group(0)}); only NSE/BSE stocks are allowed.")
    if answer.get("answer_type") == "stock_analysis" and not answer.get("verdict"):
        issues.append("Stock analysis is missing a BUY/SELL/HOLD verdict.")
    return issues


def validator_node(state: AgentState) -> dict:
    answer = state.get("final_answer") or {}
    evidence = state.get("evidence") or []
    if answer.get("answer_type") == "general":
        return {"validation": {"status": "skipped", "checks": [], "issues": [], "attempts": state.get("attempts", 1)}}

    ids = {e["id"] for e in evidence}
    issues = _deterministic_checks(answer, ids, state.get("target_tickers") or [])

    judge = get_structured_llm(ValidationVerdict, temperature=0)
    verdict: ValidationVerdict = judge.invoke([
        SystemMessage(
            "You are the Validation Agent. Check the draft answer against the evidence. Flag ONLY material problems:\n"
            "- a claim whose numbers or facts are not supported by the evidence it cites\n"
            "- an explanation that contradicts the scorecard (the BUY/SELL/HOLD verdict itself is computed by the scorecard and is correct by definition)\n"
            "- describing missing data (available=false) as if it were known\n"
            "- any non-Indian security\n"
            "Rounded numbers (e.g. 26.53 for 26.52708, or 1,234 for 1234.4) are CORRECT. Minor wording issues are not problems.\n"
            "Report ONLY issues that would mislead a reader. If there are none, return passed=true with an empty list.\n"
            "Interpretive phrases (e.g. 'suggests', 'indicates') are fine if the underlying numbers are right.\n\n"
            f"=== EVIDENCE ===\n{evidence_digest(evidence, max_chars=1200)}"),
        HumanMessage(f"=== DRAFT ANSWER ===\n{json.dumps(answer, indent=1)}"),
    ])
    if not verdict.passed:
        # Drop nitpicks about formatting/rounding - they are not factual problems.
        noise = ("rounding", "rounded", "decimal", "minor", "formatting", "trailing zero")
        issues += [i for i in verdict.issues if not any(w in i.lower() for w in noise)]

    n_claims = sum(len(s.get("claims", [])) for s in answer.get("sections", []))
    n_cited = sum(1 for s in answer.get("sections", []) for c in s.get("claims", []) if c.get("citations"))
    attempts = int(state.get("attempts") or 1)
    status = "passed" if not issues else ("revising" if attempts < MAX_ATTEMPTS else "warning")
    return {
        "validation": {"status": status, "issues": issues, "claims": n_claims, "cited_claims": n_cited,
                       "evidence_items": len(evidence), "attempts": attempts},
        "validation_feedback": issues,
    }


def after_validation(state: AgentState) -> str:
    return "synthesis_node" if (state.get("validation") or {}).get("status") == "revising" else "__end__"
