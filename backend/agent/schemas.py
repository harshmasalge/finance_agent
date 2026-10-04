"""Pydantic schemas shared by the agents, the API and (mirrored) the frontend."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Intent = Literal["research", "comparison", "sentiment", "portfolio", "ideas", "clarify", "direct_answer"]
AnswerType = Literal["stock_analysis", "comparison", "portfolio_health", "ideas", "sentiment", "general"]


class OrchestratorDecision(BaseModel):
    intent: Intent = Field(description=(
        "research: analyse one stock; comparison: compare 2+ stocks; sentiment: only news/sentiment of a stock; "
        "portfolio: health, risk, allocation or P&L of the user's own portfolio; ideas: what new stocks to consider/add; "
        "clarify: ambiguous request missing a needed stock name; direct_answer: greeting or general question needing no data."
    ))
    target_tickers: List[str] = Field(default_factory=list, description="Indian stocks mentioned, as NSE tickers like 'TECHM.NS'. Empty if none.")
    reasoning: str = Field(description="One sentence on why this intent was chosen.")
    clarification_question: Optional[str] = Field(default=None, description="Only when intent is clarify.")


class Finding(BaseModel):
    statement: str = Field(description="One factual statement, with the specific numbers from the tool output.")
    evidence_ids: List[str] = Field(description="evidence_id values of the tool outputs that support this statement.")


class AgentReport(BaseModel):
    summary: str = Field(description="2-3 sentence summary of what the data shows.")
    signal: Optional[Literal["BULLISH", "BEARISH", "NEUTRAL", "MIXED"]] = Field(default=None, description="Overall read of the data, if applicable.")
    confidence: float = Field(ge=0, le=1, description="How strongly the evidence supports the signal (0-1). Lower it when data is missing or conflicting.")
    findings: List[Finding] = Field(description="Every finding must cite at least one evidence_id.")
    data_gaps: List[str] = Field(default_factory=list, description="Data that was unavailable or unreliable.")


class Claim(BaseModel):
    text: str = Field(description="One concise sentence. Include concrete numbers where available.")
    citations: List[str] = Field(default_factory=list, description="Evidence ids (e.g. 'R2', 'P1') supporting the sentence.")


class Section(BaseModel):
    title: str
    claims: List[Claim]


class FinalAnswer(BaseModel):
    answer_type: AnswerType
    headline: str = Field(description="One or two sentence direct answer to the user's question.")
    verdict: Optional[Literal["BUY", "SELL", "HOLD"]] = Field(default=None, description="Only for stock_analysis (and optionally comparison). Null otherwise.")
    verdict_ticker: Optional[str] = Field(default=None, description="The stock the verdict refers to.")
    confidence: Optional[float] = Field(default=None, ge=0, le=1, description="Confidence in the verdict (0-1). Null when there is no verdict.")
    sections: List[Section] = Field(default_factory=list)
    data_gaps: List[str] = Field(default_factory=list, description="What data was missing and how it limits the answer.")


class ValidationVerdict(BaseModel):
    passed: bool = Field(description="True only if there are no material problems.")
    issues: List[str] = Field(default_factory=list, description="Specific problems, each naming the claim it concerns.")
