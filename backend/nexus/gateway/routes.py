"""A2A Gateway routes — inbound task submission.

Implements the A2A protocol endpoints:
- GET  /.well-known/agent.json  → Agent Card
- POST /a2a/tasks               → Submit a task
- GET  /a2a/tasks/{task_id}     → Poll task status

Authenticated via bearer token (see auth.py).
"""
from __future__ import annotations

from uuid import uuid4

import structlog
from litestar import Controller, Request, get, post

from nexus.gateway.auth import validate_token
from nexus.gateway.schemas import (
    A2ATaskRequest,
    A2ATaskResponse,
    AgentCard,
)
from nexus.kafka.producer import publish
from nexus.kafka.schemas import AgentCommand
from nexus.kafka.topics import Topics

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
        self, request: Request, data: A2ATaskRequest
    ) -> A2ATaskResponse | dict[str, str]:
        """Accept a task from an external agent.

        Validates the bearer token, creates a task record, publishes
        to the a2a.inbound Kafka topic, and returns the task ID.

        Args:
            request: The HTTP request (for auth header extraction).
            data: The A2A task request body.

        Returns:
            A2ATaskResponse with the assigned task ID.
        """
        # Authenticate
        token = _extract_token(request)
        is_valid, error = validate_token(token, skill_id=data.skill_id)
        if not is_valid:
            return {"error": error}

        # Create task
        task_id = uuid4()
        trace_id = uuid4()

        instruction = data.input.get("instruction", "")
        if not instruction:
            instruction = data.input.get("topic", str(data.input))

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
        self, task_id: str
    ) -> dict[str, str]:
        """Poll the status of an A2A task.

        Returns current task status. For Phase 2, this is a read-only
        endpoint that returns the last known state.

        Args:
            task_id: The task ID returned from submit_task.

        Returns:
            Dict with task_id, status, and optional output/error.
        """
        # Phase 2: Return a placeholder. Full DB polling in Phase 3.
        return {
            "task_id": task_id,
            "status": "accepted",
            "message": "Task is being processed. Use events endpoint for real-time updates.",
        }
