from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import AlertLog, AlertFeedback
from backend.services.auth import AuthService
from pydantic import BaseModel

alerts_router = APIRouter(prefix="/alerts", tags=["Alerts"])

class FeedbackRequest(BaseModel):
    is_positive: bool

@alerts_router.get("")
def get_alerts(user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    alerts = db.query(AlertLog).filter(AlertLog.user_id == user_id).order_by(AlertLog.created_at.desc()).limit(30).all()
    return alerts

@alerts_router.patch("/{alert_id}/read")
def mark_alert_read(alert_id: int, user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    alert = db.query(AlertLog).filter(AlertLog.id == alert_id, AlertLog.user_id == user_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    alert.is_read = True
    db.commit()
    return {"message": "Alert marked as read"}

@alerts_router.post("/{alert_id}/feedback")
def submit_feedback(alert_id: int, request: FeedbackRequest, user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    alert = db.query(AlertLog).filter(AlertLog.id == alert_id, AlertLog.user_id == user_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    feedback = AlertFeedback(alert_id=alert_id, user_id=user_id, is_positive=request.is_positive)
    db.add(feedback)
    db.commit()
    return {"message": "Feedback recorded"}

@alerts_router.get("/unread-count")
def get_unread_count(user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    count = db.query(AlertLog).filter(AlertLog.user_id == user_id, AlertLog.is_read == False).count()
    return {"count": count}
