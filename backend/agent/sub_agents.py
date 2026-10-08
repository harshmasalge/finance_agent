"""Research, sentiment and risk sub-agents. Each is a ReAct agent whose tool calls are
recorded as evidence and whose final output is a structured AgentReport."""
from typing import Callable, Dict, List, Optional, Tuple

from langgraph.prebuilt import create_react_agent

from backend.agent.evidence import track_tools
from backend.agent.schemas import AgentReport
from backend.agent.state import AgentState
from backend.agent.tools.fundamentals import get_fundamentals
from backend.agent.tools.ml_pipeline import extract_prophet_features, get_xgboost_signal
from backend.agent.tools.portfolio_tools import get_portfolio_position, get_portfolio_risk_summary
from backend.agent.tools.screener import screen_nifty_stocks
from backend.agent.tools.sentiment_tools import get_recent_headlines, get_sentiment_score
from backend.agent.tools.technical import get_technical_indicators
from backend.agent.utils import get_llm, get_structured_llm
from langchain_core.messages import HumanMessage, SystemMessage
from datetime import date
from backend.rag.tool import search_filings

COMMON_RULES = """
Rules:
- Use ONLY the data returned by your tools. Never use outside knowledge for numbers, news or events.
- Every tool result carries an `evidence_id`. Each finding you report must cite the evidence_id(s) it came from.
- If a tool returns available=false or an error, record it under data_gaps. Never fill the gap with a guess
  (e.g. missing sentiment is UNKNOWN, not "stable" or "neutral").
- Only Indian NSE/BSE stocks are in scope.
- Be specific: quote the actual numbers."""


def _today_line() -> str:
    return f"\nToday's date is {date.today():%d %b %Y}. Data dated up to today is current, not 'future-dated'."


def _run_agent(name: str, prefix: str, funcs: List[Callable], prompt: str, state: AgentState,
               extra: Optional[List[Tuple[str, List[Callable]]]] = None) -> Dict:
    """Run one ReAct agent. `extra` adds tool groups with their own evidence prefix (e.g. F for filings)."""
    evidence: List[Dict] = []
    tools = track_tools(funcs, prefix=prefix, agent=name, sink=evidence)
    for extra_prefix, extra_funcs in extra or []:
        tools += track_tools(extra_funcs, prefix=extra_prefix, agent=name, sink=evidence)
    agent = create_react_agent(get_llm(), tools=tools, prompt=prompt + COMMON_RULES + _today_line())
    try:
        result = agent.invoke({"messages": state["messages"][-6:]}, config={"recursion_limit": 16})
        # Turn the tool-calling transcript into a structured report with our own helper, which
        # picks json_schema or function calling depending on what the model supports.
        report = get_structured_llm(AgentReport, temperature=0).invoke([
            SystemMessage(prompt + COMMON_RULES + _today_line()),
            *result["messages"],
            # End on a user turn: some providers (e.g. Anthropic) reject a forced structured
            # answer that follows an assistant message.
            HumanMessage(content="Now write your final AgentReport from the tool results above. "
                                 "Every finding must cite the evidence_id(s) it came from."),
        ])
        report = report.model_dump() if report else {
            "summary": "The agent did not return a structured report.", "signal": None, "confidence": 0.0,
            "findings": [], "data_gaps": ["Agent output could not be parsed."]}
    except Exception as e:
        report = {"summary": f"{name} failed: {e}", "signal": None, "confidence": 0.0, "findings": [],
                  "data_gaps": [f"{name} could not complete: {e}"]}
    report["agent"] = name
    return {"report": report, "evidence": evidence}


def research_node(state: AgentState) -> dict:
    intent = state.get("intent")
    tickers = state.get("target_tickers") or []
    held = state.get("held_tickers") or []
    if intent == "ideas":
        task = (f"The user wants ideas for new stocks to consider. They already hold: {held or 'nothing'}.\n"
                f"1. Call screen_nifty_stocks with exclude={held} to get candidates.\n"
                "2. For the top 3 candidates call get_fundamentals so valuation and sector are known.\n"
                "Report each candidate's momentum and fundamentals, and note sector overlap with current holdings.")
    else:
        task = (f"Analyse these stocks: {', '.join(tickers)}.\n"
                "For EACH ticker call get_technical_indicators, get_fundamentals, get_xgboost_signal and extract_prophet_features.\n"
                "Weigh the XGBoost signal by its holdout_accuracy. Point out conflicting signals explicitly.\n"
                "Also call search_filings(ticker, query) 1-2 times per ticker for what the company itself reports in its "
                "annual report / earnings calls (e.g. 'management guidance and outlook', 'asset quality GNPA NNPA' for banks, "
                "'deal wins TCV and margin' for IT). Quote figures exactly as written in a passage and cite its F-id. "
                "If it returns available=false, note 'no filings indexed' as a data gap - do not guess.")
    prompt = f"You are the Research Agent of FinSight AI (Indian equities).\n{task}"
    out = _run_agent("Research Agent", "R",
                     [get_technical_indicators, get_fundamentals, get_xgboost_signal, extract_prophet_features, screen_nifty_stocks],
                     prompt, state, extra=[("F", [search_filings])] if intent != "ideas" else None)
    return {"research_output": out["report"], "evidence": out["evidence"]}


def sentiment_node(state: AgentState) -> dict:
    tickers = state.get("target_tickers") or []
    prompt = (f"You are the Sentiment Agent of FinSight AI.\nTickers: {', '.join(tickers)}.\n"
              "For EACH ticker call get_recent_headlines and get_sentiment_score. Only treat a headline as relevant if it is "
              "actually about that company; say so when the headlines are mostly about peers or the sector. "
              "The sentiment score is the average of per-article scores: when you describe it, name the specific "
              "articles (title and source) that pull it up or down, and say whether it was stored or computed now.")
    out = _run_agent("Sentiment Agent", "S", [get_recent_headlines, get_sentiment_score], prompt, state)
    return {"sentiment_output": out["report"], "evidence": out["evidence"]}


def risk_node(state: AgentState) -> dict:
    user_id = int(state.get("user_id", 1))
    tickers = state.get("target_tickers") or []

    # Bind user_id so the LLM never has to pass (or guess) it.
    def get_portfolio_summary() -> dict:
        """Whole portfolio at current prices: cash, market value, P&L, weights per holding and concentration flags."""
        return get_portfolio_risk_summary(user_id)

    def get_position(ticker: str) -> dict:
        """The user's holding in one NSE/BSE stock (quantity, avg cost, P&L, stop-loss/target), or held=false."""
        return get_portfolio_position(user_id, ticker)

    task = ("Call get_portfolio_summary. " +
            (f"Then call get_position for each of: {', '.join(tickers)}, and assess how adding to them would change concentration."
             if tickers else "Assess diversification, concentration (>30% in one stock is high), cash level and P&L."))
    prompt = f"You are the Risk Agent of FinSight AI, assessing the user's paper-trading portfolio.\n{task}"
    out = _run_agent("Risk Agent", "P", [get_portfolio_summary, get_position], prompt, state)
    return {"risk_output": out["report"], "evidence": out["evidence"]}

