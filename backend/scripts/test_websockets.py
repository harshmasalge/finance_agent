import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import asyncio
import json
import websockets
import structlog
import redis.asyncio as redis

logger = structlog.get_logger(__name__)

async def test_websocket():
    user_id = "test_user_123"
    uri = f"ws://localhost:8001/ws/{user_id}"
    
    logger.info("Connecting to WebSocket server...", uri=uri)
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("Connected successfully.")
            
            # Start a background task to publish a fake price tick to Redis
            async def publish_fake_tick():
                await asyncio.sleep(1) # wait a second for listener to be ready
                r = redis.from_url("redis://localhost:6379/0")
                payload = json.dumps({"ticker": "RELIANCE.NS", "price": 2500.50})
                await r.publish("live_prices", payload)
                logger.info("Published fake tick to Redis")
                await r.aclose()
                
            asyncio.create_task(publish_fake_tick())
            
            # Wait for the message from the websocket
            logger.info("Waiting for real-time message...")
            message = await websocket.recv()
            data = json.loads(message)
            logger.info("Received WebSocket message!", ws_event=data.get("event"), payload=data.get("data"))
            
    except Exception as e:
        logger.error("WebSocket test failed", error=str(e))
        logger.warning("Make sure the FastAPI server is running! (uvicorn backend.main:app --port 8000)")

if __name__ == "__main__":
    asyncio.run(test_websocket())
