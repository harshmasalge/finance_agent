"""Review tables. Created by `Base.metadata.create_all` once the lead imports this module in main.py.

There are deliberately no foreign keys to `chat_messages`: feedback is training data and
published research notes are an external record, so they must survive a chat being deleted.
"""
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from backend.db.database import Base


class AnswerStatus(Base):
    """Review state of one assistant message (one row per reviewed answer)."""
    __tablename__ = "answer_status"

    message_id = Column(Integer, primary_key=True)
    status = Column(String(20), nullable=False, default="draft")  # draft | approved | rejected
    current_version = Column(Integer, nullable=False, default=1)
    approved_version = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AnswerRevision(Base):
    """An immutable snapshot of an answer. Version 1 is the agent's original output."""
    __tablename__ = "answer_revisions"
    __table_args__ = (UniqueConstraint("message_id", "version", name="uq_revision_version"),)

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, index=True, nullable=False)
    version = Column(Integer, nullable=False)
    answer = Column(JSON, nullable=False)
    scorecards = Column(JSON, nullable=True)
    evidence = Column(JSON, nullable=True)
    author = Column(String(20), nullable=False, default="agent")  # agent | analyst
    feedback_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    """One natural-language correction from an analyst, and what the Correction Agent did with it."""
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, index=True, nullable=False)
    tickers = Column(JSON, nullable=True)
    from_version = Column(Integer, nullable=True)
    to_version = Column(Integer, nullable=True)
    correction_text = Column(Text, nullable=False)
    category = Column(String(20), nullable=False)  # fact | judgement | weighting | format
    target = Column(String(200), nullable=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    change_log = Column(JSON, nullable=True)
    agent_response = Column(Text, nullable=True)
    accepted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ResearchNote(Base):
    """An approved answer as a publishable research note, plus the connector outcome."""
    __tablename__ = "research_notes"
    __table_args__ = (UniqueConstraint("message_id", "version", name="uq_note_version"),)

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, index=True, nullable=False)
    version = Column(Integer, nullable=False)
    ticker = Column(String(50), nullable=True, index=True)
    title = Column(String(300), nullable=False)
    verdict = Column(String(10), nullable=True)
    body = Column(JSON, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    connector_status = Column(String(20), nullable=False, default="pending")  # pending | published | received | failed
    connector_response = Column(JSON, nullable=True)
