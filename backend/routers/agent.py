from fastapi import APIRouter, Depends
import structlog
from backend.services.auth import AuthService
from pydantic import BaseModel
from typing import List, Optional, Any

logger = structlog.get_logger(__name__)

agent_router = APIRouter(prefix="/agent", tags=["Agent"])

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: List[ChatMessage]

@agent_router.post("/chat")
def chat_with_agent(request: ChatRequest, user_id: int = Depends(AuthService.get_current_user_id)):
    logger.info("Agent chat requested", user_id=user_id, message=request.message, history_length=len(request.conversation_history))
    
    # Return stub response
    return {
        "response": "AI brain not yet connected. LangGraph integration coming next.",
        "signal": None,
        "confidence": None,
        "sources_used": []
    }
