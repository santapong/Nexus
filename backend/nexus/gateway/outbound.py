"""A2A Gateway outbound — placeholder for Phase 3.

Will support Nexus calling out to external A2A-compatible agents.
Phase 2 focuses on inbound only (receiving tasks from others).
"""
from __future__ import annotations

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class OutboundRequest(BaseModel):
    """Request to send a task to an external A2A agent."""

    target_url: str
    skill_id: str = "general"
    instruction: str = ""
    bearer_token: str = ""


class OutboundResponse(BaseModel):
    """Response from sending a task to an external agent."""

    task_id: str
    status: str
    stream_url: str = ""


async def send_task_to_external_agent(
    request: OutboundRequest,
) -> OutboundResponse:
    """Send a task to an external A2A-compatible agent (Phase 3).

    This is a placeholder. In Phase 3, this will:
    1. Discover the external agent's Agent Card
    2. Submit a task to their /a2a/tasks endpoint
    3. Stream the results back via SSE

    Args:
        request: The outbound request details.

    Returns:
        OutboundResponse (placeholder).

    Raises:
        NotImplementedError: Always — this is Phase 3 work.
    """
    logger.info(
        "a2a_outbound_placeholder",
        target_url=request.target_url,
        skill_id=request.skill_id,
    )
    raise NotImplementedError(
        "A2A outbound is not yet implemented. "
        "Planned for Phase 3."
    )
