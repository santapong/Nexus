from __future__ import annotations

import json
from typing import Any

from nexus.redis.clients import redis_working


async def get_working_memory(agent_id: str, task_id: str) -> dict[str, Any]:
    """Load agent working memory for a specific task from Redis db:0."""
    key = f"working:{agent_id}:{task_id}"
    data = await redis_working.get(key)
    if data is None:
        return {}
    return json.loads(data)  # type: ignore[no-any-return]


async def set_working_memory(agent_id: str, task_id: str, data: dict[str, Any]) -> None:
    """Save agent working memory for a specific task to Redis db:0."""
    key = f"working:{agent_id}:{task_id}"
    await redis_working.set(key, json.dumps(data), ex=14400)  # 4h TTL


async def clear_working_memory(agent_id: str, task_id: str) -> None:
    """Clear agent working memory after task completion."""
    key = f"working:{agent_id}:{task_id}"
    await redis_working.delete(key)
