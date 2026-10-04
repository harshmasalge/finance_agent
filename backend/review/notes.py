"""Learning loop: accepted analyst feedback becomes evidence (prefix `A`) for future answers."""
from datetime import timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.review.models import Feedback


def analyst_notes_for(tickers: List[str], db: Optional[Session] = None, limit: int = 5, start: int = 1) -> List[dict]:
    """Evidence items (ids A1, A2, ...) built from accepted analyst corrections about `tickers`, newest first.

    Each item has the standard evidence shape; `output` contains `ticker` so scorecard grouping and
    the Sources panel treat it like any other ticker-specific evidence.
    """
    wanted = {t.upper() for t in tickers or []}
    if not wanted:
        return []
    own = db is None
    db = db or SessionLocal()
    try:
        rows = (db.query(Feedback).filter(Feedback.accepted.is_(True), Feedback.to_version.isnot(None),
                                          Feedback.category.in_(("fact", "judgement", "weighting")))
                .order_by(Feedback.id.desc()).limit(200).all())
        items: List[dict] = []
        for f in rows:
            hit = next((t for t in (f.tickers or []) if t.upper() in wanted), None)
            if not hit:
                continue
            created = f.created_at.replace(tzinfo=f.created_at.tzinfo or timezone.utc).isoformat() if f.created_at else None
            items.append({
                "id": f"A{start + len(items)}", "agent": "Analyst Review", "tool": "analyst_note",
                "input": {"ticker": hit, "feedback_id": f.id},
                "output": {"ticker": hit, "available": True, "note": f.correction_text, "category": f.category,
                           "agent_response": f.agent_response, "message_id": f.message_id, "recorded_at": created},
                "created_at": created,
            })
            if len(items) >= limit:
                break
        return items
    finally:
        if own:
            db.close()
