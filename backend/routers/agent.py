import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from backend.agent.graph import app as langgraph_app
from backend.agent.runs import Run, get_run, json_safe, is_running, start_run, user_runs
from backend.agent.utils import config_diagnostics, list_providers, resolve, use_llm
from backend.app_mode import require_demo_mode
from backend.db.database import SessionLocal
from backend.db.models import ChatMessage, ChatSession
from backend.services.auth import get_current_user_id

logger = structlog.get_logger(__name__)
agent_router = APIRouter(prefix="/agent", tags=["Agent"])

NODE_LABELS = {
    "orchestrator_node": "Orchestrator",
    "research_node": "Research Agent",
    "sentiment_node": "Sentiment Agent",
    "risk_node": "Risk Agent",
    "synthesis_node": "Synthesis Agent",
    "validator_node": "Validation Agent",
}
INTENT_AGENTS = {
    "research": ["research_node", "sentiment_node", "risk_node"],
    "comparison": ["research_node", "sentiment_node", "risk_node"],
    "sentiment": ["sentiment_node"],
    "portfolio": ["risk_node"],
    "ideas": ["research_node", "risk_node"],
}


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None


@agent_router.get("/providers")
def get_providers():
    """LLM providers/models the UI can offer (only ones with a key in .env are 'available')."""
    return {"providers": list_providers(), "default": use_llm(None, None), **config_diagnostics()}


def _answer_as_text(payload: dict) -> str:
    """Flatten a stored structured answer into plain text for conversation memory."""
    a = (payload or {}).get("answer") or {}
    lines = [a.get("headline", "")]
    if a.get("verdict"):
        lines.append(f"Verdict: {a['verdict']} {a.get('verdict_ticker') or ''}")
    for s in a.get("sections", []):
        lines.append(f"{s['title']}: " + " ".join(c["text"] for c in s.get("claims", [])))
    return "\n".join(l for l in lines if l)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@agent_router.post("/chat", dependencies=[Depends(require_demo_mode)])
async def chat_with_agent(request: ChatRequest, user_id: int = Depends(get_current_user_id)):
    db = SessionLocal()
    try:
        chat = None
        if request.session_id:
            chat = db.query(ChatSession).filter(ChatSession.id == request.session_id, ChatSession.user_id == user_id).first()
        if chat and is_running(chat.id):
            raise HTTPException(status_code=409, detail="The agents are still working on this chat - wait for the answer first.")
        if not chat:
            title = request.message.strip().replace("\n", " ")
            chat = ChatSession(user_id=user_id, title=(title[:60] + "…") if len(title) > 60 else title or "New chat")
            db.add(chat)
            db.commit()
            db.refresh(chat)

        history = []
        for m in chat.messages[-10:]:
            history.append(HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=_answer_as_text(m.payload) or m.content))
        db.add(ChatMessage(session_id=chat.id, role="user", content=request.message))
        chat.updated_at = datetime.now(timezone.utc)
        db.commit()
        chat_id, chat_title = chat.id, chat.title
    finally:
        db.close()

    logger.info("Agent chat", user_id=user_id, chat_id=chat_id)

    llm_sel = resolve(request.provider, request.model)

    async def work(run: Run):
        llm = use_llm(request.provider, request.model)  # context-local; inherited by every agent in this run
        run.emit({"type": "session", "session_id": chat_id, "title": chat_title, "llm": llm})
        state = {"user_id": user_id, "session_id": str(chat_id), "messages": history + [HumanMessage(content=request.message)]}
        final: dict = {}
        evidence: list = []
        steps: list = []
        started = datetime.now(timezone.utc)
        try:
            run.emit({"type": "step", "node": "orchestrator_node", "label": "Orchestrator", "status": "running",
                        "detail": "Understanding your question"})
            async for update in langgraph_app.astream(state, stream_mode="updates", config={"recursion_limit": 30}):
                for node, out in update.items():
                    out = out or {}
                    final.update({k: v for k, v in out.items() if k != "evidence"})
                    evidence.extend(out.get("evidence") or [])
                    step = {"node": node, "label": NODE_LABELS.get(node, node), "status": "done",
                            "tools": [{"id": e["id"], "tool": e["tool"], "input": e["input"]} for e in (out.get("evidence") or [])]}

                    if node == "orchestrator_node":
                        tickers = out.get("target_tickers") or []
                        step["detail"] = f"Intent: {out.get('intent')}" + (f" · {', '.join(tickers)}" if tickers else "")
                        steps.append(step)
                        run.emit({"type": "step", **step})
                        for agent in INTENT_AGENTS.get(out.get("intent"), []):
                            run.emit({"type": "step", "node": agent, "label": NODE_LABELS[agent], "status": "running"})
                        if not INTENT_AGENTS.get(out.get("intent")):
                            run.emit({"type": "step", "node": "synthesis_node", "label": NODE_LABELS["synthesis_node"], "status": "running"})
                        continue

                    if node in ("research_node", "sentiment_node", "risk_node"):
                        report = out.get(node.replace("_node", "_output")) or {}
                        n_tools = len(out.get("evidence") or [])
                        step["detail"] = f"{n_tools} tool call{'s' if n_tools != 1 else ''}" + (f" · {report.get('signal')}" if report.get("signal") else "")
                    elif node == "synthesis_node":
                        step["detail"] = "Drafted answer" if (out.get("attempts") or 1) == 1 else "Revised answer after review"
                        if out.get("scorecards"):
                            step["detail"] = "Scored signals · " + ", ".join(f"{c['ticker'].split('.')[0]} {c['verdict']} ({c['score']:+.0f})" for c in out["scorecards"]) + " · drafted answer"
                    elif node == "validator_node":
                        v = out.get("validation") or {}
                        step["detail"] = {"passed": f"All {v.get('cited_claims', 0)} claims backed by evidence",
                                          "revising": f"{len(v.get('issues', []))} issue(s) found, revising",
                                          "warning": f"{len(v.get('issues', []))} issue(s) remain",
                                          "skipped": "No data claims to check"}.get(v.get("status"), "")
                    steps.append(step)
                    run.emit({"type": "step", **step})

                    # Announce the next running step
                    if node in ("research_node", "sentiment_node", "risk_node") and \
                            all(any(s["node"] == a for s in steps) for a in INTENT_AGENTS.get(final.get("intent"), [])):
                        run.emit({"type": "step", "node": "synthesis_node", "label": NODE_LABELS["synthesis_node"], "status": "running"})
                    if node == "synthesis_node":
                        run.emit({"type": "step", "node": "validator_node", "label": NODE_LABELS["validator_node"], "status": "running"})
                    if node == "validator_node" and (out.get("validation") or {}).get("status") == "revising":
                        run.emit({"type": "step", "node": "synthesis_node", "label": NODE_LABELS["synthesis_node"], "status": "running", "detail": "Revising"})

            answer = final.get("final_answer") or {"answer_type": "general", "headline": "Sorry, I could not generate a response."}
            payload = {
                "answer": answer,
                "evidence": evidence,
                "validation": final.get("validation"),
                "scorecards": final.get("scorecards") or [],
                "intent": final.get("intent"),
                "tickers": final.get("target_tickers") or [],
                "agent_reports": {k: final.get(k) for k in ("research_output", "sentiment_output", "risk_output") if final.get(k)},
                "steps": steps,
                "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
                "llm": llm,
            }
            payload = json_safe(payload)
            db2 = SessionLocal()
            try:
                msg = ChatMessage(session_id=chat_id, role="assistant", content=answer.get("headline", ""), payload=payload)
                db2.add(msg)
                db2.query(ChatSession).filter(ChatSession.id == chat_id).update({"updated_at": datetime.now(timezone.utc)})
                db2.commit()
                db2.refresh(msg)
                message_id = msg.id
            finally:
                db2.close()
            run.emit({"type": "final", "message_id": message_id, "session_id": chat_id, "payload": payload})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("LangGraph error", error=str(e))
            run.emit({"type": "error", "content": f"Something went wrong: {e}"})


    run = start_run(Run(chat_id, user_id, request.message, llm_sel), work)
    return _stream(run)


def _stream(run: Run, after: int = 0) -> StreamingResponse:
    """Watch a run over SSE. Closing the connection stops watching, not the run."""
    async def events():
        async for ev in run.follow(after):
            yield _sse(ev)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@agent_router.get("/runs")
def list_runs(user_id: int = Depends(get_current_user_id)):
    """Agent runs in progress (or finished in the last few minutes) for this user."""
    return [r.summary() for r in user_runs(user_id)]


@agent_router.get("/runs/{chat_id}/events")
def follow_run(chat_id: int, after: int = 0, user_id: int = Depends(get_current_user_id)):
    """Re-attach to a run (after navigating away or reloading): replays events from `after`."""
    run = get_run(chat_id, user_id)
    if not run:
        raise HTTPException(status_code=404, detail="No agent run for this chat")
    return _stream(run, after)
