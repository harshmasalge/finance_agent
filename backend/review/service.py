"""Review workflow on top of the review tables: lazy v1, corrections, approve/reject, notes, export.

All functions take an open SQLAlchemy session and commit their own changes.
"""
import copy
import json
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from sqlalchemy.orm import Session

from backend.db.models import ChatMessage, ChatSession
from backend.review.correction import CorrectionAgent
from backend.review.models import AnswerRevision, AnswerStatus, Feedback, ResearchNote

STATUSES = ("draft", "approved", "rejected")


class ReviewError(Exception):
    """A workflow error that maps to an HTTP status code."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


# ---------------------------------------------------------------- loading
def get_message(db: Session, message_id: int, user_id: Optional[int] = None) -> ChatMessage:
    """Load a reviewable assistant message (404 if missing / not the user's, 400 if it has no structured answer)."""
    q = db.query(ChatMessage).filter(ChatMessage.id == message_id)
    if user_id is not None:
        q = q.join(ChatSession, ChatSession.id == ChatMessage.session_id).filter(ChatSession.user_id == user_id)
    msg = q.first()
    if not msg:
        raise ReviewError(404, "Message not found")
    if msg.role != "assistant" or not isinstance(msg.payload, dict) or not isinstance(msg.payload.get("answer"), dict):
        raise ReviewError(400, "Only assistant answers can be reviewed")
    return msg


def ensure_v1(db: Session, msg: ChatMessage) -> AnswerStatus:
    """Create the review state lazily: version 1 is the agent's original payload, status draft."""
    st = db.get(AnswerStatus, msg.id)
    if st:
        return st
    p = msg.payload or {}
    db.add(AnswerRevision(message_id=msg.id, version=1, answer=copy.deepcopy(p["answer"]),
                          scorecards=copy.deepcopy(p.get("scorecards") or []), evidence=copy.deepcopy(p.get("evidence") or []),
                          author="agent"))
    st = AnswerStatus(message_id=msg.id, status="draft", current_version=1)
    db.add(st)
    db.commit()
    db.refresh(st)
    return st


def get_revision(db: Session, message_id: int, version: int) -> Optional[AnswerRevision]:
    return db.query(AnswerRevision).filter(AnswerRevision.message_id == message_id, AnswerRevision.version == version).first()


def _revisions(db: Session, message_id: int) -> List[AnswerRevision]:
    return db.query(AnswerRevision).filter(AnswerRevision.message_id == message_id).order_by(AnswerRevision.version).all()


def feedback_to_dict(f: Feedback) -> dict:
    return {"id": f.id, "message_id": f.message_id, "from_version": f.from_version, "to_version": f.to_version,
            "correction_text": f.correction_text, "category": f.category, "target": f.target, "accepted": f.accepted,
            "change_log": f.change_log or [], "agent_response": f.agent_response, "created_at": _iso(f.created_at)}


def note_summary(n: ResearchNote) -> dict:
    return {"id": n.id, "message_id": n.message_id, "version": n.version, "ticker": n.ticker, "title": n.title,
            "verdict": n.verdict, "published_at": _iso(n.published_at), "connector_status": n.connector_status}


def review_meta(st: AnswerStatus) -> dict:
    return {"status": st.status, "version": st.current_version, "approved_version": st.approved_version}


def payload_for(msg: ChatMessage, rev: AnswerRevision, st: AnswerStatus) -> dict:
    """The chat payload with the answer/scorecards/evidence of `rev` and a `review` block."""
    p = copy.deepcopy(msg.payload or {})
    p.update(answer=copy.deepcopy(rev.answer), scorecards=copy.deepcopy(rev.scorecards or []),
             evidence=copy.deepcopy(rev.evidence if rev.evidence is not None else p.get("evidence") or []))
    p["review"] = {**review_meta(st), "shown_version": rev.version}
    return p


def review_state(db: Session, msg: ChatMessage) -> dict:
    """Everything the ReviewBar needs: status, all versions, feedback thread, published notes, current payload."""
    st = ensure_v1(db, msg)
    revs = _revisions(db, msg.id)
    cur = next(r for r in revs if r.version == st.current_version)
    fb = db.query(Feedback).filter(Feedback.message_id == msg.id).order_by(Feedback.id).all()
    notes = db.query(ResearchNote).filter(ResearchNote.message_id == msg.id).order_by(ResearchNote.version).all()
    return {
        "message_id": msg.id, **review_meta(st), "current_version": st.current_version, "updated_at": _iso(st.updated_at),
        "versions": [{"version": r.version, "author": r.author, "feedback_id": r.feedback_id, "created_at": _iso(r.created_at),
                      "answer": r.answer, "scorecards": r.scorecards or []} for r in revs],
        "feedback": [feedback_to_dict(f) for f in fb],
        "notes": [note_summary(n) for n in notes],
        "payload": payload_for(msg, cur, st),
    }


def _sync_chat_payload(msg: ChatMessage, rev: AnswerRevision, st: AnswerStatus) -> None:
    """Keep chat_messages.payload showing the current version, so reopening the chat shows the corrected answer."""
    msg.payload = payload_for(msg, rev, st)
    msg.content = (rev.answer or {}).get("headline", msg.content)


# ---------------------------------------------------------------- actions
def correct(db: Session, msg: ChatMessage, text: str, target: Optional[str], agent: CorrectionAgent) -> dict:
    """Run the Correction Agent on the current version, log the feedback, and create a new version if it changed."""
    text = (text or "").strip()
    if not text:
        raise ReviewError(422, "Correction text is empty")
    st = ensure_v1(db, msg)
    cur = get_revision(db, msg.id, st.current_version)
    tickers = (msg.payload or {}).get("tickers") or []
    outcome = agent.run(cur.answer, cur.evidence or [], cur.scorecards or [], text, target=target, tickers=tickers)
    res = outcome.result
    fb = Feedback(message_id=msg.id, tickers=tickers, from_version=cur.version, correction_text=text, category=res.category,
                  target=target, before=cur.answer, after=outcome.answer if outcome.changed else None,
                  change_log=[e.model_dump() for e in res.change_log], agent_response=outcome.agent_response,
                  accepted=res.accepted)
    db.add(fb)
    db.flush()
    new_rev = None
    if outcome.changed:
        new_rev = AnswerRevision(message_id=msg.id, version=cur.version + 1, answer=outcome.answer, scorecards=outcome.scorecards,
                                 evidence=outcome.evidence, author="analyst", feedback_id=fb.id)
        db.add(new_rev)
        fb.to_version = new_rev.version
        st.current_version = new_rev.version
        st.status = "draft"  # an edited answer must be approved again
        st.updated_at = _now()
        _sync_chat_payload(msg, new_rev, st)
    db.commit()
    state = review_state(db, msg)
    return {"feedback": feedback_to_dict(fb), "accepted": res.accepted, "category": res.category, "pushback": res.pushback,
            "change_log": fb.change_log, "agent_response": outcome.agent_response, "source": outcome.source,
            "new_version": new_rev.version if new_rev else None, "weight_changes": outcome.weight_changes, "review": state}


def reject(db: Session, msg: ChatMessage, reason: Optional[str] = None) -> dict:
    """Mark the answer rejected; it can no longer be published until corrected and approved."""
    st = ensure_v1(db, msg)
    st.status, st.updated_at = "rejected", _now()
    if reason and reason.strip():
        db.add(Feedback(message_id=msg.id, tickers=(msg.payload or {}).get("tickers") or [], from_version=st.current_version,
                        correction_text=reason.strip(), category="judgement", accepted=False,
                        agent_response="Answer rejected by the analyst.", before=get_revision(db, msg.id, st.current_version).answer))
    _sync_chat_payload(msg, get_revision(db, msg.id, st.current_version), st)
    db.commit()
    return review_state(db, msg)


def _question_for(db: Session, msg: ChatMessage) -> Optional[str]:
    prev = (db.query(ChatMessage).filter(ChatMessage.session_id == msg.session_id, ChatMessage.id < msg.id, ChatMessage.role == "user")
            .order_by(ChatMessage.id.desc()).first())
    return prev.content if prev else None


def build_note(db: Session, msg: ChatMessage, rev: AnswerRevision) -> dict:
    """The research-note document that is pushed to the platform."""
    a = rev.answer or {}
    cards = rev.scorecards or []
    ticker = a.get("verdict_ticker") or ((msg.payload or {}).get("tickers") or [None])[0]
    card = next((c for c in cards if c.get("ticker") == ticker), cards[0] if cards else None)
    fb = (db.query(Feedback).filter(Feedback.message_id == msg.id, Feedback.accepted.is_(True),
                                    Feedback.to_version.isnot(None), Feedback.to_version <= rev.version).order_by(Feedback.id).all())
    used = {x for s in a.get("sections") or [] for c in s.get("claims") or [] for x in c.get("citations") or []}
    title = a.get("headline") or "Research note"
    if ticker and a.get("verdict"):
        title = f"{ticker.split('.')[0]}: {a['verdict']} - {title}"
    return {
        "schema": "finsight.research_note/v1",
        "message_id": msg.id, "version": rev.version, "ticker": ticker, "title": title[:300],
        "question": _question_for(db, msg), "answer_type": a.get("answer_type"), "headline": a.get("headline"),
        "verdict": a.get("verdict"), "confidence": a.get("confidence"), "sections": a.get("sections") or [],
        "data_gaps": a.get("data_gaps") or [],
        "scorecard": ({k: card.get(k) for k in ("ticker", "score", "verdict", "confidence", "thresholds", "overrides")} |
                      {"factors": [{k: f.get(k) for k in ("name", "label", "score", "weight", "reason", "evidence_id")} for f in card.get("factors") or []]})
        if card else None,
        "sources": [{"id": e["id"], "agent": e.get("agent"), "tool": e.get("tool"), "input": e.get("input"),
                     "as_of": (e.get("output") or {}).get("as_of") if isinstance(e.get("output"), dict) else None}
                    for e in rev.evidence or [] if e.get("id") in used],
        "review": {"approved_at": _now().isoformat(), "revisions": rev.version,
                   "corrections": [{"text": f.correction_text, "category": f.category, "version": f.to_version} for f in fb]},
    }


def note_markdown(body: dict) -> str:
    """Render a research note as Markdown (for export)."""
    lines = [f"# {body.get('title')}", ""]
    meta = [f"**Verdict:** {body['verdict']}" if body.get("verdict") else None,
            f"**Confidence:** {round(body['confidence'] * 100)}%" if body.get("confidence") is not None else None,
            f"**Version:** v{body.get('version')} (analyst-approved)"]
    lines += [" · ".join(m for m in meta if m), ""]
    if body.get("question"):
        lines += [f"> {body['question']}", ""]
    lines += [body.get("headline") or "", ""]
    sc = body.get("scorecard")
    if sc:
        lines += [f"## Signal scorecard ({sc.get('ticker')}: {sc.get('score'):+} → {sc.get('verdict')})", "",
                  "| Factor | Score | Weight | Reason |", "|---|---:|---:|---|"]
        lines += [f"| {f['label']} | {f['score']:+.2f} | {f['weight']:g} | {f['reason']} |" for f in sc.get("factors") or []]
        lines.append("")
    for s in body.get("sections") or []:
        lines += [f"## {s['title']}", ""]
        lines += [f"- {c['text']}" + (f" [{', '.join(c.get('citations') or [])}]" if c.get("citations") else "") for c in s.get("claims") or []]
        lines.append("")
    if body.get("data_gaps"):
        lines += ["## Data gaps", ""] + [f"- {g}" for g in body["data_gaps"]] + [""]
    if body.get("sources"):
        lines += ["## Sources", ""] + [f"- **{x['id']}** {x.get('agent')} · {x.get('tool')}" + (f" (as of {x['as_of']})" if x.get("as_of") else "")
                                       for x in body["sources"]] + [""]
    corr = (body.get("review") or {}).get("corrections") or []
    if corr:
        lines += ["## Analyst corrections", ""] + [f"- v{c.get('version')}: {c['text']} ({c['category']})" for c in corr] + [""]
    return "\n".join(lines).strip() + "\n"


def approve(db: Session, msg: ChatMessage, version: Optional[int], connector) -> dict:
    """Approve a version (default: current) and push it through the connector. Re-approving is idempotent."""
    st = ensure_v1(db, msg)
    version = version or st.current_version
    rev = get_revision(db, msg.id, version)
    if not rev:
        raise ReviewError(404, f"Version {version} does not exist")
    st.status, st.approved_version, st.updated_at = "approved", version, _now()
    note = db.query(ResearchNote).filter(ResearchNote.message_id == msg.id, ResearchNote.version == version).first()
    if not note or note.connector_status != "published":
        # Always (re)build an unpublished note from the approved revision: a row with the same (message_id, version)
        # may have been POSTed to /research-notes directly, and its body must never be published as if approved.
        body = build_note(db, msg, rev)
        if not note:
            note = ResearchNote(message_id=msg.id, version=version, connector_status="pending")
            db.add(note)
        note.ticker, note.title, note.verdict, note.body = body["ticker"], body["title"], body["verdict"], body
        if note.connector_status == "received":
            note.connector_status, note.connector_response, note.published_at = "pending", None, None
    _sync_chat_payload(msg, get_revision(db, msg.id, st.current_version), st)
    db.commit()
    db.refresh(note)
    result = connector.publish(note)
    db.refresh(note)
    return {"publish": result, "note": note_summary(note), "review": review_state(db, msg)}


def platform_receive(db: Session, body: dict) -> dict:
    """The research platform side (`POST /research-notes`): store a note, idempotent on (message_id, version)."""
    try:
        mid, ver = int(body["message_id"]), int(body["version"])
    except (KeyError, TypeError, ValueError):
        raise ReviewError(422, "A note needs integer message_id and version")
    if mid < 1 or ver < 1:
        raise ReviewError(422, "message_id and version must be positive")
    if body.get("verdict") not in (None, "BUY", "SELL", "HOLD"):
        raise ReviewError(422, "verdict must be BUY, SELL, HOLD or null")
    if body.get("ticker") is not None and (not isinstance(body["ticker"], str) or len(body["ticker"]) > 50):
        raise ReviewError(422, "ticker must be a string of at most 50 characters")
    if len(json.dumps(body, default=str)) > 200_000:
        raise ReviewError(413, "Note body is too large")
    note = db.query(ResearchNote).filter(ResearchNote.message_id == mid, ResearchNote.version == ver).first()
    if note:
        return {"status": "published", "id": note.id, "url": f"/research-notes/{note.id}", "duplicate": True}
    note = ResearchNote(message_id=mid, version=ver, ticker=body.get("ticker"), title=str(body.get("title") or "Research note")[:300],
                        verdict=body.get("verdict"), body=body, connector_status="received", published_at=_now())
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"status": "published", "id": note.id, "url": f"/research-notes/{note.id}", "duplicate": False}


# ---------------------------------------------------------------- training data
def export_feedback(db: Session) -> Iterator[str]:
    """One JSON object per line per correction: the input answer, the analyst's text, the agent's decision and the output.

    Accepted corrections are supervised examples (before -> after); rejected ones are pushback examples.
    """
    questions = {}
    for f in db.query(Feedback).order_by(Feedback.id).yield_per(200):
        if f.message_id not in questions:
            m = db.get(ChatMessage, f.message_id)
            questions[f.message_id] = _question_for(db, m) if m else None
        yield json.dumps({
            "id": f.id, "created_at": _iso(f.created_at), "message_id": f.message_id, "question": questions[f.message_id],
            "tickers": f.tickers or [], "from_version": f.from_version, "to_version": f.to_version,
            "correction": f.correction_text, "target": f.target, "category": f.category, "accepted": f.accepted,
            "label": "accepted_correction" if f.accepted and f.to_version else "no_change" if f.accepted else "rejected_correction",
            "agent_response": f.agent_response, "change_log": f.change_log or [], "before": f.before, "after": f.after,
        }, ensure_ascii=False, default=str) + "\n"
