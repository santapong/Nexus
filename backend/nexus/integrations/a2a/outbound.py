"""A2A Gateway outbound — NEXUS hires external A2A agents.

Supports the full outbound flow:
1. Discover external agent via /.well-known/agent.json
2. Submit a task to their /a2a/tasks endpoint
3. Poll status or stream results via SSE
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx
import structlog
from pydantic import BaseModel

from nexus.integrations.a2a.schemas import AgentCard

logger = structlog.get_logger()

_DEFAULT_TIMEOUT = 60.0
_SSE_TIMEOUT = 600.0


# ─── Models ───────────────────────────────────────────────────────────────────


class OutboundRequest(BaseModel):
    """Request to send a task to an external A2A agent."""

    target_url: str
    skill_id: str = "general"
    instruction: str = ""
    bearer_token: str = ""
    metadata: dict[str, Any] = {}


class OutboundResponse(BaseModel):
    """Response from sending a task to an external agent."""

    task_id: str
    status: str
    stream_url: str = ""


class ExternalAgentResult(BaseModel):
    """Final result from an external agent."""

    task_id: str
    status: str
    output: dict[str, Any] | None = None
    error: str | None = None


# ─── Discovery ────────────────────────────────────────────────────────────────


async def discover_agent(base_url: str) -> AgentCard:
    """Fetch an external agent's Agent Card.

    Args:
        base_url: The agent's base URL (e.g., https://agent.example.com).

    Returns:
        Parsed AgentCard with skills and capabilities.

    Raises:
        httpx.HTTPStatusError: If the request fails.
        ValueError: If the card cannot be parsed.
    """
    url = f"{base_url.rstrip('/')}/.well-known/agent.json"
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    logger.info(
        "a2a_agent_discovered",
        base_url=base_url,
        agent_name=data.get("name", "unknown"),
        skills_count=len(data.get("skills", [])),
    )
    return AgentCard(**data)


# ─── Task submission ──────────────────────────────────────────────────────────


async def submit_task(
    target_url: str,
    request: OutboundRequest,
) -> OutboundResponse:
    """Submit a task to an external A2A agent.

    Args:
        target_url: The agent's /a2a/tasks endpoint URL.
        request: The outbound task request.

    Returns:
        OutboundResponse with the external task ID and stream URL.

    Raises:
        httpx.HTTPStatusError: If the submission is rejected.
    """
    payload = {
        "skill_id": request.skill_id,
        "input": {"instruction": request.instruction},
        "metadata": {
            "caller": "nexus-agent",
            **request.metadata,
        },
    }
    headers = {}
    if request.bearer_token:
        headers["Authorization"] = f"Bearer {request.bearer_token}"

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        response = await client.post(target_url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    logger.info(
        "a2a_task_submitted",
        target_url=target_url,
        task_id=data.get("task_id"),
        status=data.get("status"),
    )

    return OutboundResponse(
        task_id=data["task_id"],
        status=data.get("status", "accepted"),
        stream_url=data.get("stream_url", ""),
    )


# ─── Status polling ──────────────────────────────────────────────────────────


async def poll_status(
    status_url: str,
    bearer_token: str = "",
) -> ExternalAgentResult:
    """Poll an external agent for task status.

    Args:
        status_url: The status endpoint URL.
        bearer_token: Bearer token for authentication.

    Returns:
        ExternalAgentResult with current status.
    """
    headers = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        response = await client.get(status_url, headers=headers)
        response.raise_for_status()
        data = response.json()

    return ExternalAgentResult(
        task_id=data.get("task_id", ""),
        status=data.get("status", "unknown"),
        output=data.get("output"),
        error=data.get("error"),
    )


# ─── SSE streaming ───────────────────────────────────────────────────────────


async def stream_results(
    stream_url: str,
    bearer_token: str = "",
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream task results from an external agent via SSE.

    Args:
        stream_url: The SSE endpoint URL.
        bearer_token: Bearer token for authentication.

    Yields:
        Parsed event dicts from the SSE stream.
    """
    import json

    headers = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    async with (
        httpx.AsyncClient(timeout=_SSE_TIMEOUT) as client,
        client.stream("GET", stream_url, headers=headers) as response,
    ):
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:].strip()
                if not data_str:
                    continue
                try:
                    event = json.loads(data_str)
                    yield event
                    if event.get("event_type") == "done":
                        return
                except json.JSONDecodeError:
                    logger.warning(
                        "a2a_sse_parse_error",
                        line=data_str[:200],
                    )


# ─── High-level hire flow ─────────────────────────────────────────────────────


async def hire_external_agent(
    *,
    agent_url: str,
    instruction: str,
    skill_id: str = "general",
    bearer_token: str = "",
    use_streaming: bool = False,
) -> ExternalAgentResult:
    """Complete flow: discover -> submit -> poll/stream -> return result.

    Args:
        agent_url: Base URL of the external agent.
        instruction: What to ask the external agent to do.
        skill_id: Which skill to request.
        bearer_token: Auth token for the external agent.
        use_streaming: If True, use SSE streaming instead of polling.

    Returns:
        The external agent's final result.
    """
    import asyncio

    # 1. Discover
    card = await discover_agent(agent_url)
    logger.info(
        "a2a_hiring",
        agent_name=card.name,
        skill_id=skill_id,
    )

    # 2. Submit
    tasks_url = f"{agent_url.rstrip('/')}/a2a/tasks"
    request = OutboundRequest(
        target_url=tasks_url,
        skill_id=skill_id,
        instruction=instruction,
        bearer_token=bearer_token,
    )
    submission = await submit_task(tasks_url, request)

    # 3. Get result
    if use_streaming and submission.stream_url:
        stream_url = f"{agent_url.rstrip('/')}{submission.stream_url}"
        last_event: dict[str, Any] = {}
        async for event in stream_results(stream_url, bearer_token):
            last_event = event
            if event.get("event") in ("task_result", "task_failed"):
                return ExternalAgentResult(
                    task_id=submission.task_id,
                    status=event.get("status", "completed"),
                    output=event.get("output"),
                    error=event.get("error"),
                )
        return ExternalAgentResult(
            task_id=submission.task_id,
            status=last_event.get("status", "unknown"),
            output=last_event.get("output"),
            error=last_event.get("error"),
        )

    # Polling fallback: poll every 5s for up to 10 minutes
    status_url = f"{agent_url.rstrip('/')}/a2a/tasks/{submission.task_id}/status"
    for _ in range(120):
        result = await poll_status(status_url, bearer_token)
        if result.status in ("completed", "failed"):
            return result
        await asyncio.sleep(5)

    return ExternalAgentResult(
        task_id=submission.task_id,
        status="timeout",
        error="External agent did not complete within 10 minutes",
    )
