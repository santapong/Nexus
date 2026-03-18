"""WebSocket endpoint for real-time dashboard updates via Redis pub/sub."""

from __future__ import annotations

import structlog
from litestar import WebSocket, websocket

from nexus.integrations.redis.clients import redis_pubsub

logger = structlog.get_logger()


@websocket("/ws/agents")
async def agent_activity_ws(socket: WebSocket) -> None:
    """Stream agent activity events to the dashboard in real-time.

    Subscribes to Redis pub/sub pattern agent_activity:* and forwards
    all messages to the connected WebSocket client.
    """
    await socket.accept()
    logger.info("websocket_connected", client=str(socket.client))

    pubsub = redis_pubsub.pubsub()
    await pubsub.psubscribe("agent_activity:*")

    try:
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                data = message.get("data", "")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await socket.send_text(data)
    except Exception as exc:
        logger.info("websocket_disconnected", reason=str(exc))
    finally:
        await pubsub.punsubscribe("agent_activity:*")
        await socket.close()
