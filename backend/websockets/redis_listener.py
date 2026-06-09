import asyncio
import json
import structlog
import redis.asyncio as redis
from backend.websockets.manager import manager
from backend.celery_app import REDIS_URL

logger = structlog.get_logger(__name__)

async def redis_listener():
    """
    Background task that listens to Redis Pub/Sub channels
    and broadcasts events to connected WebSocket clients.
    """
    logger.info("Starting Redis Pub/Sub listener...")
    r = redis.from_url(REDIS_URL)
    pubsub = r.pubsub()
    
    # Subscribe to relevant channels
    await pubsub.subscribe("live_prices", "user_alerts")
    
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                channel = message["channel"].decode("utf-8")
                data = json.loads(message["data"].decode("utf-8"))
                
                if channel == "live_prices":
                    # Broadcast live prices to all connected clients
                    await manager.broadcast_all({
                        "event": "price_update",
                        "data": data
                    })
                elif channel == "user_alerts":
                    # Broadcast alert only to the specific user
                    user_id = data.get("user_id")
                    if user_id:
                        await manager.broadcast_to_user(str(user_id), {
                            "event": "alert",
                            "data": data
                        })
    except asyncio.CancelledError:
        logger.info("Redis listener cancelled.")
    except Exception as e:
        logger.error("Redis listener encountered an error", error=str(e))
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()
