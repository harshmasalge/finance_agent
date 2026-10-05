from backend.app_mode import require_demo_mode
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import ChatMessage, ChatSession
from backend.services.auth import get_current_user_id

chats_router = APIRouter(prefix="/chats", tags=["Chats"])


class RenameRequest(BaseModel):
    title: str


def _session_or_404(db: Session, user_id: int, chat_id: int) -> ChatSession:
    chat = db.query(ChatSession).filter(ChatSession.id == chat_id, ChatSession.user_id == user_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


def message_to_dict(m: ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "payload": m.payload,
            "created_at": m.created_at.isoformat() if m.created_at else None}


@chats_router.get("")
def list_chats(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    chats = (db.query(ChatSession).filter(ChatSession.user_id == user_id)
             .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc()).limit(100).all())
    return [{"id": c.id, "title": c.title,
             "created_at": c.created_at.isoformat() if c.created_at else None,
             "updated_at": c.updated_at.isoformat() if c.updated_at else None} for c in chats]


@chats_router.get("/{chat_id}")
def get_chat(chat_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    chat = _session_or_404(db, user_id, chat_id)
    return {"id": chat.id, "title": chat.title, "messages": [message_to_dict(m) for m in chat.messages]}


@chats_router.patch("/{chat_id}")
def rename_chat(chat_id: int, req: RenameRequest, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    chat = _session_or_404(db, user_id, chat_id)
    chat.title = req.title.strip()[:200] or chat.title
    db.commit()
    return {"id": chat.id, "title": chat.title}


@chats_router.delete("/{chat_id}", dependencies=[Depends(require_demo_mode)])
def delete_chat(chat_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    chat = _session_or_404(db, user_id, chat_id)
    db.delete(chat)
    db.commit()
    return {"message": "Chat deleted"}
