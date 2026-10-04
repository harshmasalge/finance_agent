import logging
import structlog
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend.websockets.manager import manager
from backend.websockets.redis_listener import redis_listener
from backend.services.auth import get_or_create_default_user
from backend.db.database import get_db, engine, Base
from backend.db.models import User
from sqlalchemy.orm import Session
from backend.routers.portfolio import portfolio_router
from backend.routers.alerts import alerts_router
from backend.routers.agent import agent_router
from backend.routers.chats import chats_router
from backend.review.router import router as review_router
import backend.review.models  # noqa: F401  registers answer_status, answer_revisions, feedback, research_notes

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up FastAPI and background tasks...")
    # Create any missing tables so the app works even if init_db.py wasn't run
    Base.metadata.create_all(bind=engine)
    task = asyncio.create_task(redis_listener())
    yield
    task.cancel()

app = FastAPI(
    title="FinSight AI API",
    description="Agentic AI Stock Market Advisor",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(portfolio_router)
app.include_router(alerts_router)
app.include_router(agent_router)
app.include_router(chats_router)
app.include_router(review_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class HealthResponse(BaseModel):
    status: str
    message: str

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Basic health check endpoint to verify the API is running.
    """
    logger.info("Health check endpoint called")
    return HealthResponse(status="ok", message="FinSight AI API is running")

@app.get("/")
async def root():
    return {"message": "Welcome to FinSight AI"}

@app.get("/me")
def get_me(db: Session = Depends(get_db)):
    """Returns the (single) default user. There is no login in FinSight."""
    user = get_or_create_default_user(db)
    return {"id": user.id, "email": user.email, "name": user.name, "picture": user.picture, "balance": user.virtual_balance}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for real-time updates.
    """
    await manager.connect(websocket, user_id)
    try:
        while True:
            # We don't necessarily expect incoming messages, but we keep the connection open
            data = await websocket.receive_text()
            logger.info("Received WS message", user_id=user_id, data=data)
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
