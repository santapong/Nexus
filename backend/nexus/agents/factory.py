"""Agent construction factory.

Builds fully configured agent instances with the correct model,
tools, topics, and database session factory.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent as PydanticAgent

from nexus.agents.base import AgentBase, ToolCallLimitExceededError
from nexus.core.kafka.topics import Topics
from nexus.core.llm.factory import ModelFactory
from nexus.db.models import AgentRole
from nexus.tools.registry import get_tools_for_role

# Kafka topic subscriptions per role
ROLE_TOPICS: dict[AgentRole, list[str]] = {
    AgentRole.CEO: [Topics.TASK_QUEUE, Topics.AGENT_RESPONSES, Topics.A2A_INBOUND],
    AgentRole.DIRECTOR: [Topics.DIRECTOR_REVIEW],
    AgentRole.ENGINEER: [Topics.AGENT_COMMANDS],
    AgentRole.ANALYST: [Topics.AGENT_COMMANDS],
    AgentRole.WRITER: [Topics.AGENT_COMMANDS],
    AgentRole.QA: [Topics.TASK_REVIEW_QUEUE],
    AgentRole.PROMPT_CREATOR: [Topics.PROMPT_IMPROVEMENT, Topics.PROMPT_BENCHMARK],
}


def _wrap_tools_with_counter(
    tools: list[Any],
    counter: dict[str, int],
) -> list[Any]:
    """Wrap each tool function with a call counter that enforces MAX_TOOL_CALLS.

    Args:
        tools: List of Pydantic AI tool functions.
        counter: Mutable dict with 'count' and 'limit' keys.

    Returns:
        List of wrapped tool functions.
    """
    wrapped: list[Any] = []
    for tool_fn in tools:

        @functools.wraps(tool_fn)
        async def counted_tool(*args: Any, _original: Any = tool_fn, **kwargs: Any) -> Any:
            counter["count"] += 1
            if counter["count"] > counter["limit"]:
                raise ToolCallLimitExceededError(f"Tool call limit ({counter['limit']}) exceeded")
            return await _original(*args, **kwargs)

        wrapped.append(counted_tool)
    return wrapped


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
    model = ModelFactory.get_model_with_fallbacks(role)
    tools = get_tools_for_role(role)

    # Wrap tools with call counter for limit enforcement
    tool_counter: dict[str, int] = {"count": 0, "limit": AgentBase.MAX_TOOL_CALLS}
    counted_tools = _wrap_tools_with_counter(tools, tool_counter) if tools else []

    llm_agent = PydanticAgent(
        model=model,
        system_prompt=system_prompt,
        tools=counted_tools,
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

    agent: AgentBase

    if role == AgentRole.CEO:
        from nexus.agents.ceo import CEOAgent

        agent = CEOAgent(**kwargs)  # type: ignore[arg-type]
    elif role == AgentRole.DIRECTOR:
        from nexus.agents.director import DirectorAgent

        agent = DirectorAgent(**kwargs)  # type: ignore[arg-type]
    elif role == AgentRole.ENGINEER:
        from nexus.agents.engineer import EngineerAgent

        agent = EngineerAgent(**kwargs)  # type: ignore[arg-type]
    elif role == AgentRole.ANALYST:
        from nexus.agents.analyst import AnalystAgent

        agent = AnalystAgent(**kwargs)  # type: ignore[arg-type]
    elif role == AgentRole.WRITER:
        from nexus.agents.writer import WriterAgent

        agent = WriterAgent(**kwargs)  # type: ignore[arg-type]
    elif role == AgentRole.QA:
        from nexus.agents.qa import QAAgent

        agent = QAAgent(**kwargs)  # type: ignore[arg-type]
    elif role == AgentRole.PROMPT_CREATOR:
        from nexus.agents.prompt_creator import PromptCreatorAgent

        agent = PromptCreatorAgent(**kwargs)  # type: ignore[arg-type]
    else:
        msg = f"No agent implementation for role: {role.value}"
        raise ValueError(msg)

    # Attach tool call counter so base.py can reset it per task
    agent._tool_call_counter = tool_counter  # type: ignore[union-attr]
    # Store system prompt text for hot-reload detection
    agent._current_system_prompt = system_prompt
    return agent
