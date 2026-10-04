from typing import List

from langchain_core.prompts import ChatPromptTemplate

from backend.agent.schemas import OrchestratorDecision
from backend.agent.state import AgentState
from backend.agent.utils import get_structured_llm
from backend.db.database import SessionLocal
from backend.db.models import Portfolio

ORCHESTRATOR_PROMPT = """You are the Orchestrator of FinSight AI, a research assistant for Indian equities (NSE/BSE) with a paper-trading portfolio.
Classify the user's LATEST message (use the conversation for context, e.g. "what about Infosys?" after a TCS analysis is research on INFY.NS).

Intents:
- research: analyse a specific stock ("how is Tech Mahindra", "should I buy TCS")
- comparison: compare two or more specific stocks
- sentiment: only the news / sentiment around a stock
- portfolio: the user's own portfolio - health, risk, allocation, P&L, what to trim
- ideas: which new stocks to look at / add / diversify into
- clarify: a stock-specific question that names no stock and the context does not make it clear
- direct_answer: greetings, thanks, or general finance questions that need no data

Convert company names to NSE tickers with the .NS suffix (Tech Mahindra -> TECHM.NS, Infosys -> INFY.NS, Reliance -> RELIANCE.NS, HDFC Bank -> HDFCBANK.NS, SBI -> SBIN.NS, L&T -> LT.NS, M&M -> M&M.NS).
Never output non-Indian tickers."""


def _held_tickers(user_id: int) -> List[str]:
    db = SessionLocal()
    try:
        rows = db.query(Portfolio.ticker).filter(Portfolio.user_id == user_id, Portfolio.quantity > 0).all()
        return [t for (t,) in rows]
    except Exception:
        return []
    finally:
        db.close()


def orchestrator_node(state: AgentState) -> dict:
    llm = get_structured_llm(OrchestratorDecision, temperature=0)
    prompt = ChatPromptTemplate.from_messages([("system", ORCHESTRATOR_PROMPT), ("placeholder", "{messages}")])
    decision: OrchestratorDecision = (prompt | llm).invoke({"messages": state["messages"][-8:]})

    tickers = [t.strip().upper() for t in decision.target_tickers if t.strip()]
    tickers = [t if t.endswith((".NS", ".BO")) else f"{t}.NS" for t in tickers]
    intent = decision.intent
    if intent in ("research", "sentiment") and not tickers:
        intent = "clarify"
    if intent == "comparison" and len(tickers) < 2:
        intent = "research" if tickers else "clarify"

    return {
        "intent": intent,
        "target_tickers": tickers,
        "orchestrator_reasoning": decision.reasoning,
        "clarification_question": decision.clarification_question,
        "held_tickers": _held_tickers(state.get("user_id", 1)),
        "attempts": 0,
        "validation_feedback": [],
    }


ROUTES = {
    "research": ["research_node", "sentiment_node", "risk_node"],
    "comparison": ["research_node", "sentiment_node", "risk_node"],
    "sentiment": ["sentiment_node"],
    "portfolio": ["risk_node"],
    "ideas": ["research_node", "risk_node"],
}


def router_edge(state: AgentState) -> List[str]:
    return ROUTES.get(state.get("intent"), ["synthesis_node"])
