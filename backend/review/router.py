"""FastAPI routes for expert review (`/review`) and the research-notes platform (`/research-notes`)."""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.review import service
from backend.review.connector import NotPublishable, ResearchNotesConnector
from backend.review.correction import CorrectionAgent, LLMUnavailable
from backend.review.models import ResearchNote
from backend.services.auth import get_current_user_id

router = APIRouter(tags=["Review"])


class CorrectRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000, description="The analyst's correction in plain English.")
    target: Optional[str] = Field(default=None, max_length=200, description="Optional path/label the correction is about.")


class ApproveRequest(BaseModel):
    version: Optional[int] = Field(default=None, ge=1, description="Version to approve; defaults to the current one.")


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


def get_correction_agent() -> CorrectionAgent:
    """Dependency: the Correction Agent with the production LLM (overridden in tests)."""
    return CorrectionAgent()


def get_connector(db: Session = Depends(get_db)) -> ResearchNotesConnector:
    """Dependency: the platform connector (overridden in tests)."""
    return ResearchNotesConnector(db)


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.ReviewError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except NotPublishable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LLMUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/review/feedback/export.jsonl")
def export_feedback(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """All analyst feedback as JSONL training data."""
    return StreamingResponse(service.export_feedback(db), media_type="application/x-ndjson",
                             headers={"Content-Disposition": 'attachment; filename="finsight_feedback.jsonl"'})


@router.get("/review/{message_id}")
def get_review(message_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """Review state of an answer (creates version 1 on first access)."""
    return _guard(lambda: service.review_state(db, service.get_message(db, message_id, user_id)))


@router.post("/review/{message_id}/correct")
def correct(message_id: int, req: CorrectRequest, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id),
            agent: CorrectionAgent = Depends(get_correction_agent)):
    """Apply a natural-language correction; returns the agent's explanation/pushback and the new review state."""
    return _guard(lambda: service.correct(db, service.get_message(db, message_id, user_id), req.text, req.target, agent))


@router.post("/review/{message_id}/approve")
def approve(message_id: int, req: ApproveRequest = Body(default_factory=ApproveRequest), db: Session = Depends(get_db),
            user_id: int = Depends(get_current_user_id), connector: ResearchNotesConnector = Depends(get_connector)):
    """Approve a version and publish it as a research note through the connector."""
    return _guard(lambda: service.approve(db, service.get_message(db, message_id, user_id), req.version, connector))


@router.post("/review/{message_id}/reject")
def reject(message_id: int, req: RejectRequest = Body(default_factory=RejectRequest), db: Session = Depends(get_db),
           user_id: int = Depends(get_current_user_id)):
    """Reject the answer (it cannot be published until corrected and approved)."""
    return _guard(lambda: service.reject(db, service.get_message(db, message_id, user_id), req.reason))


@router.get("/research-notes")
def list_notes(db: Session = Depends(get_db)):
    """Published research notes, newest first."""
    rows = db.query(ResearchNote).order_by(ResearchNote.id.desc()).limit(200).all()
    return [service.note_summary(n) for n in rows]


@router.post("/research-notes")
def receive_note(body: dict = Body(...), db: Session = Depends(get_db)):
    """The 'platform' endpoint the connector pushes to (idempotent on message_id + version)."""
    return _guard(service.platform_receive, db, body)


@router.get("/research-notes/{note_id}")
def get_note(note_id: int, db: Session = Depends(get_db)):
    """One research note with its body, connector outcome and a Markdown rendering."""
    n = db.get(ResearchNote, note_id)
    if not n:
        raise HTTPException(status_code=404, detail="Note not found")
    return {**service.note_summary(n), "body": n.body, "connector_response": n.connector_response,
            "markdown": service.note_markdown(n.body or {})}
