from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import AlertLog, AlertFeedback
from backend.services.auth import get_current_user_id
from pydantic import BaseModel
from backend.app_mode import require_demo_mode

alerts_router = APIRouter(prefix="/alerts", tags=["Alerts"])

class FeedbackRequest(BaseModel):
    is_positive: bool

@alerts_router.get("")
def get_alerts(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    alerts = db.query(AlertLog).filter(AlertLog.user_id == user_id).order_by(AlertLog.created_at.desc()).limit(30).all()
    return alerts

@alerts_router.patch("/{alert_id}/read")
def mark_alert_read(alert_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    alert = db.query(AlertLog).filter(AlertLog.id == alert_id, AlertLog.user_id == user_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    alert.is_read = True
    db.commit()
    return {"message": "Alert marked as read"}

@alerts_router.post("/{alert_id}/feedback")
def submit_feedback(alert_id: int, request: FeedbackRequest, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    alert = db.query(AlertLog).filter(AlertLog.id == alert_id, AlertLog.user_id == user_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    feedback = AlertFeedback(alert_id=alert_id, user_id=user_id, is_positive=request.is_positive)
    db.add(feedback)
    db.commit()
    return {"message": "Feedback recorded"}

@alerts_router.get("/unread-count")
def get_unread_count(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    count = db.query(AlertLog).filter(AlertLog.user_id == user_id, AlertLog.is_read == False).count()
    return {"count": count}


@alerts_router.post("/check-now", dependencies=[Depends(require_demo_mode)])
def check_now(user_id: int = Depends(get_current_user_id)):
    """Run news-sentiment ingestion and the portfolio monitor right away (normally every 15 min in market hours)."""
    from backend.tasks.sentiment_ingestion import run_sentiment_ingestion
    from backend.tasks.portfolio_monitor import run_portfolio_monitor
    import time
    t0 = time.monotonic()
    sentiment = run_sentiment_ingestion()
    t1 = time.monotonic()
    monitor = run_portfolio_monitor()
    t2 = time.monotonic()
    return {"sentiment": sentiment, "monitor": monitor,
            "seconds": {"sentiment": round(t1 - t0, 1), "monitor": round(t2 - t1, 1)}}


@alerts_router.get("/sentiment/{ticker}")
def sentiment(ticker: str):
    """News-sentiment score for a ticker with the articles behind it (same output the Sentiment Agent sees)."""
    from backend.agent.tools.sentiment_tools import get_sentiment_score
    return get_sentiment_score(ticker)
