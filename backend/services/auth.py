"""
No-login mode: FinSight runs as a single-user app.

Every request is treated as the default user, who is created automatically
on first use. Routes keep a `user_id` dependency so multi-user auth can be
added back later without touching the routers.
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import User

DEFAULT_USER_EMAIL = "demo@finsight.ai"
DEFAULT_USER_NAME = "Demo User"


def get_or_create_default_user(db: Session) -> User:
    user = db.query(User).filter(User.email == DEFAULT_USER_EMAIL).first()
    if not user:
        user = User(
            email=DEFAULT_USER_EMAIL,
            name=DEFAULT_USER_NAME,
            picture="https://api.dicebear.com/7.x/avataaars/svg?seed=FinSight",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_current_user_id(db: Session = Depends(get_db)) -> int:
    """FastAPI dependency: always returns the default user's id."""
    return get_or_create_default_user(db).id
