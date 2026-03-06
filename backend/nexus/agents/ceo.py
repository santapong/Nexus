"""CEO Agent — thin task router for Phase 1.

In Phase 1, the CEO does not use an LLM. It simply routes all incoming
tasks from task.queue to agent.commands targeting the Engineer agent.

Full decomposition and multi-agent delegation comes in Phase 2.
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents.base import AgentBase
from nexus.db.models import AgentRole
from nexus.kafka.producer import publish
from nexus.kafka.schemas import AgentCommand, AgentResponse
from nexus.kafka.topics import Topics

logger = structlog.get_logger()


class CEOAgent(AgentBase):
    """CEO agent — Phase 1 thin router that delegates all tasks to Engineer."""

    async def handle_task(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Route task directly to the Engineer agent."""
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        logger.info(
            "ceo_delegating_task",
            task_id=task_id,
            trace_id=trace_id,
            target="engineer",
        )

        # Create a command for the Engineer
        engineer_command = AgentCommand(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload=message.payload,
            target_role=AgentRole.ENGINEER.value,
            instruction=message.instruction,
        )

        await publish(
            Topics.AGENT_COMMANDS, engineer_command, key=task_id
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={"action": "delegated_to_engineer"},
            tokens_used=0,
        )
