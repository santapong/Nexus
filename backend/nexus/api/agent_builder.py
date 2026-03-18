"""Agent Builder API — no-code custom agent creation.

Endpoints:
- GET  /api/agent-builder           — List custom agent configs
- POST /api/agent-builder           — Create a custom agent
- PUT  /api/agent-builder/{id}      — Update a custom agent config
- DELETE /api/agent-builder/{id}    — Deactivate a custom agent
- POST /api/agent-builder/{id}/activate — Activate/register the agent
"""

from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, delete, get, post, put
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Agent

logger = structlog.get_logger()


class CreateAgentRequest(BaseModel):
    """Request body for creating a new custom agent."""

    name: str
    role: str = "custom"
    system_prompt: str
    llm_model: str = "claude-haiku-4-5-20251001"
    tool_access: list[str] = Field(default_factory=lambda: ["web_search", "file_read"])
    kafka_topics: list[str] = Field(default_factory=lambda: ["agent.commands"])
    token_budget_per_task: int = 50000


class UpdateAgentRequest(BaseModel):
    """Request body for updating a custom agent configuration."""

    name: str | None = None
    system_prompt: str | None = None
    llm_model: str | None = None
    tool_access: list[str] | None = None
    token_budget_per_task: int | None = None


class AgentConfigResponse(BaseModel):
    """Public representation of an agent configuration."""

    id: str
    name: str
    role: str
    system_prompt: str
    llm_model: str
    tool_access: list[str]
    kafka_topics: list[str]
    token_budget_per_task: int
    is_active: bool


def _truncate_prompt(prompt: str, max_len: int = 200) -> str:
    """Truncate a system prompt for display purposes."""
    if len(prompt) > max_len:
        return prompt[:max_len] + "..."
    return prompt


def _agent_to_response(agent: Agent) -> AgentConfigResponse:
    """Convert an Agent ORM object to an AgentConfigResponse."""
    return AgentConfigResponse(
        id=str(agent.id),
        name=agent.name,
        role=agent.role,
        system_prompt=_truncate_prompt(agent.system_prompt),
        llm_model=agent.llm_model,
        tool_access=agent.tool_access or [],
        kafka_topics=agent.kafka_topics or [],
        token_budget_per_task=agent.token_budget_per_task,
        is_active=agent.is_active,
    )


class AgentBuilderController(Controller):
    """No-code custom agent creation and management."""

    path = "/agent-builder"

    @get()
    async def list_custom_agents(self, db_session: AsyncSession) -> list[AgentConfigResponse]:
        """List all agent configurations."""
        stmt = select(Agent).order_by(Agent.role)
        result = await db_session.execute(stmt)
        agents = result.scalars().all()

        return [_agent_to_response(a) for a in agents]

    @post()
    async def create_agent(
        self, data: CreateAgentRequest, db_session: AsyncSession
    ) -> AgentConfigResponse:
        """Create a new custom agent configuration."""
        agent = Agent(
            name=data.name,
            role=data.role,
            system_prompt=data.system_prompt,
            llm_model=data.llm_model,
            tool_access=data.tool_access,
            kafka_topics=data.kafka_topics,
            token_budget_per_task=data.token_budget_per_task,
            is_active=False,  # Must be activated explicitly
        )
        db_session.add(agent)
        await db_session.flush()
        await db_session.commit()

        logger.info(
            "custom_agent_created",
            agent_id=str(agent.id),
            name=data.name,
            role=data.role,
        )

        return _agent_to_response(agent)

    @put("/{agent_id:str}")
    async def update_agent(
        self, agent_id: str, data: UpdateAgentRequest, db_session: AsyncSession
    ) -> AgentConfigResponse | dict[str, str]:
        """Update a custom agent configuration."""
        stmt = select(Agent).where(Agent.id == agent_id)
        result = await db_session.execute(stmt)
        agent = result.scalar_one_or_none()
        if agent is None:
            return {"error": "Agent not found"}

        if data.name is not None:
            agent.name = data.name
        if data.system_prompt is not None:
            agent.system_prompt = data.system_prompt
        if data.llm_model is not None:
            agent.llm_model = data.llm_model
        if data.tool_access is not None:
            agent.tool_access = data.tool_access
        if data.token_budget_per_task is not None:
            agent.token_budget_per_task = data.token_budget_per_task

        await db_session.flush()
        await db_session.commit()

        logger.info("custom_agent_updated", agent_id=agent_id)

        return _agent_to_response(agent)

    @delete("/{agent_id:str}")
    async def deactivate_agent(self, agent_id: str, db_session: AsyncSession) -> dict[str, Any]:
        """Deactivate a custom agent."""
        stmt = select(Agent).where(Agent.id == agent_id)
        result = await db_session.execute(stmt)
        agent = result.scalar_one_or_none()
        if agent is None:
            return {"error": "Agent not found"}

        agent.is_active = False
        await db_session.flush()
        await db_session.commit()

        logger.info("custom_agent_deactivated", agent_id=agent_id)
        return {"id": agent_id, "is_active": False}

    @post("/{agent_id:str}/activate")
    async def activate_agent(self, agent_id: str, db_session: AsyncSession) -> dict[str, Any]:
        """Activate a custom agent so it starts processing tasks."""
        stmt = select(Agent).where(Agent.id == agent_id)
        result = await db_session.execute(stmt)
        agent = result.scalar_one_or_none()
        if agent is None:
            return {"error": "Agent not found"}

        agent.is_active = True
        await db_session.flush()
        await db_session.commit()

        logger.info("custom_agent_activated", agent_id=agent_id)
        return {
            "id": agent_id,
            "is_active": True,
            "message": "Agent activated. Restart agent runner to pick up changes.",
        }
