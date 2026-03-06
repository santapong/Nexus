from __future__ import annotations

import structlog
from litestar import Controller, get
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Agent

logger = structlog.get_logger()


class AgentResponse(BaseModel):
    id: str
    role: str
    name: str
    llm_model: str
    tool_access: list[str]
    is_active: bool
    token_budget_per_task: int


class AgentController(Controller):
    path = "/agents"

    @get()
    async def list_agents(self, db_session: AsyncSession) -> list[AgentResponse]:
        """List all registered agents."""
        stmt = select(Agent).order_by(Agent.role)
        result = await db_session.execute(stmt)
        agents = result.scalars().all()

        return [
            AgentResponse(
                id=str(a.id),
                role=a.role,
                name=a.name,
                llm_model=a.llm_model,
                tool_access=a.tool_access,
                is_active=a.is_active,
                token_budget_per_task=a.token_budget_per_task,
            )
            for a in agents
        ]
