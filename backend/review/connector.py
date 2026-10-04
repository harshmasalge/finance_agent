"""Platform connector: pushes approved research notes to the research-notes API.

Target: `NOTES_API_URL` (e.g. https://platform.example.com/research-notes). When it is unset or
"internal", notes go to FinSight's own `/research-notes` platform endpoint in-process.
Publishing is idempotent on (message_id, version): a published note is never sent twice, and the
`Idempotency-Key` header lets a remote platform deduplicate retries.
"""
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.review.models import AnswerStatus, ResearchNote


class NotPublishable(Exception):
    """Raised when a note's answer is not approved at that version (draft or rejected answers are never published)."""


class ResearchNotesConnector:
    """Publish `ResearchNote` rows to the configured platform and record the outcome on the row."""

    def __init__(self, db: Session, url: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None, timeout: float = 10.0):
        self.db = db
        raw = url if url is not None else os.getenv("NOTES_API_URL", "")
        self.url = None if raw.strip().lower() in ("", "internal") else raw.strip()
        self.transport, self.timeout = transport, timeout

    @staticmethod
    def idempotency_key(note: ResearchNote) -> str:
        return f"finsight-note-{note.message_id}-v{note.version}"

    def publish(self, note: ResearchNote) -> dict:
        """Send `note`; returns {status, id, ...}. Raises NotPublishable unless that exact version is approved."""
        if note not in self.db:  # the caller may hold the row in another session
            note = self.db.get(ResearchNote, note.id, populate_existing=True) or note
        st = self.db.get(AnswerStatus, note.message_id, populate_existing=True)
        if not st or st.status != "approved" or st.approved_version != note.version:
            raise NotPublishable(f"Answer {note.message_id} v{note.version} is "
                                 f"{st.status if st else 'not reviewed'}; only approved answers can be published")
        if note.connector_status == "published":
            prev = note.connector_response or {}
            return {"status": "published", "id": prev.get("id"), "idempotent": True, "response": prev}
        try:
            if self.url is None:
                from backend.review.service import platform_receive
                resp = platform_receive(self.db, note.body)
            else:
                with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                    r = client.post(self.url, json=note.body, headers={"Idempotency-Key": self.idempotency_key(note)})
                    r.raise_for_status()
                    resp = r.json() if r.content else {}
            note.connector_status = "published"
            note.connector_response = {"target": self.url or "internal", **(resp if isinstance(resp, dict) else {"body": resp})}
            note.published_at = datetime.now(timezone.utc)
            self.db.commit()
            return {"status": "published", "id": note.connector_response.get("id"), "idempotent": False, "response": note.connector_response}
        except NotPublishable:
            raise
        except Exception as e:  # network / platform error: keep the note pending-retry
            self.db.rollback()
            note.connector_status = "failed"
            note.connector_response = {"target": self.url or "internal", "error": f"{type(e).__name__}: {str(e)[:300]}"}
            self.db.commit()
            return {"status": "failed", "id": None, "error": note.connector_response["error"]}
