import operator
from typing import Annotated, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Inputs
    user_id: int
    session_id: str
    messages: Annotated[List[BaseMessage], add_messages]

    # Orchestrator
    intent: str
    target_tickers: List[str]
    orchestrator_reasoning: str
    clarification_question: Optional[str]
    held_tickers: List[str]

    # Sub-agent reports (AgentReport dicts)
    research_output: Optional[dict]
    sentiment_output: Optional[dict]
    risk_output: Optional[dict]

    # Every tool call, from every agent (merged across parallel branches)
    evidence: Annotated[List[dict], operator.add]

    # Deterministic signal scorecards (one per analysed ticker)
    scorecards: List[dict]

    # Synthesis + validation
    final_answer: Optional[dict]
    validation: Optional[dict]
    validation_feedback: List[str]
    attempts: int
