"""Behavior tests for the CEO agent routing flow.

Tests CEO task routing logic with mocked Kafka — verifies delegation
to Engineer, not LLM quality.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.agents.ceo import CEOAgent
from nexus.db.models import AgentRole
from nexus.kafka.schemas import AgentCommand


def _make_mock_llm() -> MagicMock:
    """Create an LLM mock that returns a parseable empty subtask list.

    The behavior tests only care about CEO routing, not LLM quality.
    Return empty JSON so CEO falls back to delegating to engineer.
    """
    mock_result = MagicMock()
    mock_result.output = "[]"  # Empty → CEO falls back to engineer
    mock_usage = MagicMock()
    mock_usage.request_tokens = 0
    mock_usage.response_tokens = 0
    mock_result.usage.return_value = mock_usage

    mock_llm = MagicMock()
    mock_llm.run = AsyncMock(return_value=mock_result)
    mock_llm.model = MagicMock()
    mock_llm.model.model_name = "test-model"
    return mock_llm


def _make_ceo() -> CEOAgent:
    """Build a CEOAgent with all dependencies mocked."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    return CEOAgent(
        role=AgentRole.CEO,
        agent_id="test-ceo",
        subscribe_topics=["task.queue"],
        group_id="test-ceo-group",
        llm_agent=_make_mock_llm(),
        db_session_factory=MagicMock(return_value=mock_session),
    )


def _make_task_command(instruction: str = "Build a web scraper in Python") -> AgentCommand:
    return AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="api",
        payload={"instruction": instruction},
        target_role=AgentRole.CEO.value,
        instruction=instruction,
    )


@pytest.mark.asyncio
@patch("nexus.agents.ceo.write_episode", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.record_usage", new_callable=AsyncMock)
async def test_ceo_delegates_to_engineer(
    mock_usage: AsyncMock,
    mock_wm: AsyncMock,
    mock_write_episode: AsyncMock,
) -> None:
    """CEO should publish an AgentCommand to agent.commands targeting engineer."""
    agent = _make_ceo()
    command = _make_task_command()
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    published_messages: list[tuple[str, object]] = []

    async def capture_publish(topic: str, msg: object, *, key: str | None = None) -> None:
        published_messages.append((topic, msg))

    with patch("nexus.agents.ceo.publish", side_effect=capture_publish):
        response = await agent.handle_task(command, mock_session)

    # CEO should publish exactly one message to agent.commands
    assert len(published_messages) == 1
    topic, msg = published_messages[0]
    assert topic == "agent.commands"

    assert isinstance(msg, AgentCommand)
    assert msg.target_role == AgentRole.ENGINEER.value
    assert msg.instruction == command.instruction
    assert msg.task_id == command.task_id
    assert msg.trace_id == command.trace_id


@pytest.mark.asyncio
@patch("nexus.agents.ceo.write_episode", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.record_usage", new_callable=AsyncMock)
async def test_ceo_returns_delegation_response(
    mock_usage: AsyncMock,
    mock_wm: AsyncMock,
    mock_write_episode: AsyncMock,
) -> None:
    """CEO should return a success response indicating delegation."""
    agent = _make_ceo()
    command = _make_task_command()
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    with patch("nexus.agents.ceo.publish", new_callable=AsyncMock):
        response = await agent.handle_task(command, mock_session)

    assert response.status == "success"
    assert response.output is not None
    assert response.output.get("action") == "decomposed"


@pytest.mark.asyncio
@patch("nexus.agents.ceo.write_episode", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.record_usage", new_callable=AsyncMock)
async def test_ceo_preserves_task_and_trace_ids(
    mock_usage: AsyncMock,
    mock_wm: AsyncMock,
    mock_write_episode: AsyncMock,
) -> None:
    """CEO should propagate task_id and trace_id to the delegated command."""
    agent = _make_ceo()
    task_id = uuid4()
    trace_id = uuid4()
    command = AgentCommand(
        task_id=task_id,
        trace_id=trace_id,
        agent_id="api",
        payload={},
        target_role=AgentRole.CEO.value,
        instruction="Investigate performance issue",
    )
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    captured: list[AgentCommand] = []

    async def capture(topic: str, msg: object, *, key: str | None = None) -> None:
        if isinstance(msg, AgentCommand):
            captured.append(msg)

    with patch("nexus.agents.ceo.publish", side_effect=capture):
        await agent.handle_task(command, mock_session)

    assert len(captured) == 1
    assert captured[0].task_id == task_id
    assert captured[0].trace_id == trace_id
