import os
import uuid
import json
import structlog
from typing import Optional
from fastapi import Request, Response
from backend.db.database import redis_client

logger = structlog.get_logger(__name__)

SESSION_COOKIE_NAME = "finsight_session"
SESSION_EXPIRY = 60 * 60 * 24 * 7 # 7 days

class AuthService:
    
    @staticmethod
    def create_session(response: Response, user_id: int):
        """Creates a secure Redis-backed session and sets the HTTPOnly cookie."""
        session_id = str(uuid.uuid4())
        
        # Store in Redis
        redis_client.setex(f"session:{session_id}", SESSION_EXPIRY, user_id)
        
        # Set secure HTTPOnly cookie
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            max_age=SESSION_EXPIRY,
            httponly=True,
            samesite="lax",
            secure=os.getenv("ENVIRONMENT", "development") != "development"
        )
        logger.info("Session created", user_id=user_id)

    @staticmethod
    def get_current_user_id(request: Request) -> Optional[int]:
        """Retrieves the currently logged-in user_id from the session cookie."""
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if not session_id:
            return None
            
        user_id_str = redis_client.get(f"session:{session_id}")
        if not user_id_str:
            return None
            
        return int(user_id_str)

    @staticmethod
    def delete_session(request: Request, response: Response):
        """Logs out the user by deleting the Redis key and cookie."""
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if session_id:
            redis_client.delete(f"session:{session_id}")
        
        response.delete_cookie(SESSION_COOKIE_NAME)
        logger.info("Session deleted")
