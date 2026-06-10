import logging
import structlog
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend.websockets.manager import manager
from backend.websockets.redis_listener import redis_listener
from backend.services.auth import AuthService
from backend.db.database import get_db
from backend.db.models import User
from sqlalchemy.orm import Session
from backend.routers.portfolio import portfolio_router
from backend.routers.alerts import alerts_router
from backend.routers.agent import agent_router

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

class MockLoginRequest(BaseModel):
    email: str
    name: str

@app.post("/auth/mock-login")
def mock_login(req: MockLoginRequest, response: Response, db: Session = Depends(get_db)):
    """Developer mock login endpoint."""
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        user = User(email=req.email, name=req.name, picture="https://api.dicebear.com/7.x/avataaars/svg?seed=" + req.name)
        db.add(user)
        db.commit()
        db.refresh(user)
        
    AuthService.create_session(response, user.id)
    return {"message": "Logged in successfully", "user": {"id": user.id, "email": user.email, "name": user.name}}

@app.get("/auth/me")
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Returns the currently logged-in user based on the HTTPOnly cookie."""
    user_id = AuthService.get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
        
    return {"id": user.id, "email": user.email, "name": user.name, "picture": user.picture, "balance": user.virtual_balance}

@app.post("/auth/logout")
def logout(request: Request, response: Response):
    AuthService.delete_session(request, response)
    return {"message": "Logged out successfully"}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for real-time updates.
    """
    session_user_id = AuthService.get_current_user_id(websocket)
    if str(session_user_id) != user_id:
        await websocket.close(code=1008, reason="Unauthorized")
        return
        
    await manager.connect(websocket, user_id)
    try:
        while True:
            # We don't necessarily expect incoming messages, but we keep the connection open
            data = await websocket.receive_text()
            logger.info("Received WS message", user_id=user_id, data=data)
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
