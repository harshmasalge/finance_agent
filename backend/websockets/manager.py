from typing import Dict, Set
import structlog
from fastapi import WebSocket

logger = structlog.get_logger(__name__)

class ConnectionManager:
    def __init__(self):
        # Maps user_id to a set of active WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        logger.info("Client connected", user_id=user_id, active_connections=len(self.active_connections[user_id]))

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info("Client disconnected", user_id=user_id)

    async def broadcast_to_user(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error("Failed to send message to client", error=str(e), user_id=user_id)

    async def broadcast_all(self, message: dict):
        for user_connections in self.active_connections.values():
            for connection in user_connections:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error("Failed to broadcast message", error=str(e))

manager = ConnectionManager()
