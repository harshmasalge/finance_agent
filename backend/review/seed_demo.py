"""Seed recorded answers as chats so the review flow can be demoed without LLM credits.

    python -m backend.review.seed_demo            # adds every non-general fixture answer as its own chat
    python -m backend.review.seed_demo --only policy

Uses POSTGRES_URL like the API. Safe to re-run: chats are added again with a "[demo]" title prefix.
"""
import argparse
import copy
import json
from pathlib import Path

from backend.db.database import Base, SessionLocal, engine
from backend.db import models as _core  # noqa: F401
from backend.db.models import ChatMessage, ChatSession
from backend.review import models as _review  # noqa: F401
from backend.services.auth import get_or_create_default_user

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "answers.json"


def seed(only: str = "") -> list:
    """Insert fixture Q&A pairs as chats for the default user; returns [(chat_id, assistant_message_id, question)]."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    out = []
    try:
        user = get_or_create_default_user(db)
        for f in json.loads(FIXTURES.read_text(encoding="utf-8")):
            p = f["payload"]
            if p["answer"].get("answer_type") == "general" or (only and only.lower() not in f["question"].lower()):
                continue
            chat = ChatSession(user_id=user.id, title=f"[demo] {f['question'][:50]}")
            db.add(chat)
            db.commit()
            db.add(ChatMessage(session_id=chat.id, role="user", content=f["question"]))
            msg = ChatMessage(session_id=chat.id, role="assistant", content=p["answer"].get("headline", ""), payload=copy.deepcopy(p))
            db.add(msg)
            db.commit()
            out.append((chat.id, msg.id, f["question"]))
    finally:
        db.close()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default="", help="Only questions containing this text")
    for chat_id, mid, q in seed(ap.parse_args().only):
        print(f"chat {chat_id} · message {mid} · {q}")
