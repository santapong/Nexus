"""Agent construction factory.

Builds fully configured agent instances with the correct model,
tools, topics, and database session factory.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent as PydanticAgent

from nexus.agents.base import AgentBase
from nexus.db.models import AgentRole
from nexus.kafka.topics import Topics
from nexus.llm.factory import ModelFactory
from nexus.tools.registry import get_tools_for_role

# Kafka topic subscriptions per role
ROLE_TOPICS: dict[AgentRole, list[str]] = {
    AgentRole.CEO: [Topics.TASK_QUEUE, Topics.AGENT_RESPONSES, Topics.A2A_INBOUND],
    AgentRole.ENGINEER: [Topics.AGENT_COMMANDS],
    AgentRole.ANALYST: [Topics.AGENT_COMMANDS],
    AgentRole.WRITER: [Topics.AGENT_COMMANDS],
    AgentRole.QA: [Topics.TASK_REVIEW_QUEUE],
    AgentRole.PROMPT_CREATOR: [Topics.PROMPT_IMPROVEMENT, Topics.PROMPT_BENCHMARK],
}


def build_agent(
    *,
    role: AgentRole,
    agent_id: str,
    system_prompt: str,
    db_session_factory: Callable[..., Any],
) -> AgentBase:
    """Build a fully configured agent instance.

    Args:
        role: The agent's role.
        agent_id: UUID string from the agents table.
        system_prompt: The system prompt loaded from the prompts table.
        db_session_factory: Callable returning an async session context manager.

    Returns:
        A configured AgentBase subclass instance ready to run().
    """
    model = ModelFactory.get_model(role)
    tools = get_tools_for_role(role)

    llm_agent = PydanticAgent(
        model=model,
        system_prompt=system_prompt,
        tools=tools,
    )

    topics = ROLE_TOPICS.get(role, [Topics.AGENT_COMMANDS])
    group_id = f"nexus-{role.value}"

    kwargs = {
        "role": role,
        "agent_id": agent_id,
        "subscribe_topics": topics,
        "group_id": group_id,
        "llm_agent": llm_agent,
        "db_session_factory": db_session_factory,
    }

    if role == AgentRole.CEO:
        from nexus.agents.ceo import CEOAgent
        return CEOAgent(**kwargs)

    if role == AgentRole.ENGINEER:
        from nexus.agents.engineer import EngineerAgent
        return EngineerAgent(**kwargs)

    if role == AgentRole.ANALYST:
        from nexus.agents.analyst import AnalystAgent
        return AnalystAgent(**kwargs)

    if role == AgentRole.WRITER:
        from nexus.agents.writer import WriterAgent
        return WriterAgent(**kwargs)

    if role == AgentRole.QA:
        from nexus.agents.qa import QAAgent
        return QAAgent(**kwargs)

    msg = f"No agent implementation for role: {role.value}"
    raise ValueError(msg)
