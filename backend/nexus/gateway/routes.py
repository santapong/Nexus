"""A2A Gateway routes — inbound task submission.

Implements the A2A protocol endpoints:
- GET  /.well-known/agent.json       -> Agent Card
- POST /a2a/tasks                    -> Submit a task
- GET  /a2a/tasks/{task_id}/status   -> Poll task status
- GET  /a2a/tasks/{task_id}/events   -> SSE stream

Authenticated via bearer token (see auth.py).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import structlog
from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException, TooManyRequestsException
from litestar.response import Stream
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Task, TaskSource, TaskStatus
from nexus.gateway.auth import validate_token
from nexus.gateway.rate_limiter import check_rate_limit
from nexus.gateway.schemas import (
    A2ATaskRequest,
    A2ATaskResponse,
    AgentCard,
)
from nexus.kafka.producer import publish
from nexus.kafka.schemas import AgentCommand
from nexus.kafka.topics import Topics
from nexus.redis.clients import redis_pubsub

logger = structlog.get_logger()


def _extract_token(request: Request) -> str:
    """Extract bearer token from the Authorization header.

    Args:
        request: The HTTP request.

    Returns:
        The raw token string, or empty string if missing.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return ""


class AgentCardController(Controller):
    """Serves the Agent Card at /.well-known/agent.json."""

    path = "/.well-known"

    @get("/agent.json")
    async def get_agent_card(self) -> AgentCard:
        """Return the NEXUS public Agent Card.

        Returns:
            AgentCard with skills and authentication info.
        """
        return AgentCard()


class A2AGatewayController(Controller):
    """A2A Gateway endpoints for task submission and polling."""

    path = "/a2a"

    @post("/tasks")
    async def submit_task(
        self,
        request: Request,
        data: A2ATaskRequest,
        db_session: AsyncSession,
    ) -> A2ATaskResponse:
        """Accept a task from an external agent.

        Validates the bearer token, persists a Task record to PostgreSQL,
        publishes to the a2a.inbound Kafka topic, and returns the task ID.

        Args:
            request: The HTTP request (for auth header extraction).
            data: The A2A task request body.
            db_session: Async database session (injected by Litestar).

        Returns:
            A2ATaskResponse with the assigned task ID.

        Raises:
            NotAuthorizedException: If the bearer token is invalid.
        """
        token = _extract_token(request)
        is_valid, error, rpm = await validate_token(
            token, skill_id=data.skill_id, db_session=db_session
        )
        if not is_valid:
            raise NotAuthorizedException(detail=error)

        # Rate limiting
        from nexus.gateway.auth import _hash_token

        allowed, _remaining = await check_rate_limit(
            _hash_token(token), rpm
        )
        if not allowed:
            raise TooManyRequestsException(
                detail="Rate limit exceeded. Try again later."
            )

        trace_id = uuid4()

        instruction = data.input.get("instruction", "")
        if not instruction:
            instruction = data.input.get("topic", str(data.input))

        # Persist Task record — must exist before Kafka publish so that
        # result_consumer and CEO can look it up by task_id.
        task = Task(
            trace_id=str(trace_id),
            instruction=instruction,
            status=TaskStatus.QUEUED.value,
            source=TaskSource.A2A.value,
            source_agent=data.metadata.get("caller", "unknown"),
        )
        db_session.add(task)
        await db_session.flush()
        await db_session.commit()

        task_id = task.id

        # Publish to Kafka for CEO pickup
        command = AgentCommand(
            task_id=task_id,
            trace_id=trace_id,
            agent_id="a2a-gateway",
            payload={
                "source": "a2a",
                "skill_id": data.skill_id,
                "metadata": data.metadata,
            },
            target_role="ceo",
            instruction=instruction,
        )
        await publish(Topics.A2A_INBOUND, command, key=str(task_id))

        logger.info(
            "a2a_task_accepted",
            task_id=str(task_id),
            skill_id=data.skill_id,
            instruction_preview=instruction[:100],
        )

        return A2ATaskResponse(
            task_id=str(task_id),
            status="accepted",
            stream_url=f"/a2a/tasks/{task_id}/events",
        )

    @get("/tasks/{task_id:str}/status")
    async def get_task_status(
        self, task_id: str, db_session: AsyncSession
    ) -> dict[str, Any]:
        """Poll the status of an A2A task.

        Reads current task state from PostgreSQL.

        Args:
            task_id: The task ID returned from submit_task.
            db_session: Async database session (injected by Litestar).

        Returns:
            Dict with task_id, status, output, error, and tokens_used.
        """
        stmt = select(Task).where(Task.id == task_id)
        result = await db_session.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None:
            return {"error": "Task not found", "task_id": task_id}

        return {
            "task_id": str(task.id),
            "status": task.status,
            "output": task.output,
            "error": task.error,
            "tokens_used": task.tokens_used,
        }

    @get("/tasks/{task_id:str}/events")
    async def stream_task_events(
        self,
        request: Request,
        task_id: str,
        db_session: AsyncSession,
    ) -> Stream:
        """Stream real-time task events via Server-Sent Events (SSE).

        Subscribes to Redis pub/sub channel ``agent_activity:{task_id}``
        and yields events in SSE format until the task completes or
        a 10-minute timeout is reached.

        Args:
            request: The HTTP request (for auth header extraction).
            task_id: The task ID to stream events for.
            db_session: Async database session (injected by Litestar).

        Returns:
            Stream response with ``text/event-stream`` media type.

        Raises:
            NotAuthorizedException: If the bearer token is invalid.
        """
        token = _extract_token(request)
        is_valid, error, _rpm = await validate_token(
            token, db_session=db_session
        )
        if not is_valid:
            raise NotAuthorizedException(detail=error)

        async def _event_generator() -> Any:
            pubsub = redis_pubsub.pubsub()
            channel = f"agent_activity:{task_id}"
            await pubsub.subscribe(channel)

            # Send initial connected event
            connected = {"event_type": "connected", "task_id": task_id}
            yield f"data: {json.dumps(connected)}\n\n"

            timeout_seconds = 600  # 10-minute max SSE session
            start = asyncio.get_event_loop().time()

            try:
                while (
                    asyncio.get_event_loop().time() - start
                ) < timeout_seconds:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if message and message["type"] == "message":
                        data = message.get("data", "")
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        yield f"data: {data}\n\n"

                        # Terminate on completion events
                        try:
                            parsed = json.loads(data)
                            if parsed.get("event") in (
                                "task_result",
                                "task_failed",
                            ):
                                done = {
                                    "event_type": "done",
                                    "task_id": task_id,
                                }
                                yield f"data: {json.dumps(done)}\n\n"
                                break
                        except (json.JSONDecodeError, TypeError):
                            pass
                    else:
                        # No message yet — yield a keep-alive comment
                        await asyncio.sleep(1)
            except Exception as exc:
                logger.warning(
                    "sse_stream_error",
                    task_id=task_id,
                    error=str(exc),
                )
            finally:
                await pubsub.unsubscribe(channel)

        return Stream(
            _event_generator(), media_type="text/event-stream"
        )
