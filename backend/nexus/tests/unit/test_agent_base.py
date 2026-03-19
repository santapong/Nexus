"""Unit tests for AgentBase guard chain."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.agents.base import AgentBase
from nexus.core.kafka.schemas import AgentCommand, AgentResponse
from nexus.db.models import AgentRole

# ─── Concrete test subclass ─────────────────────────────────────────────────


class FakeAgent(AgentBase):
    """Minimal concrete agent for testing the base class."""

    handle_task_mock: AsyncMock

    async def handle_task(self, message: Any, session: Any) -> Any:
        return await self.handle_task_mock(message, session)


def _make_agent(
    *,
    handle_task_return: AgentResponse | None = None,
) -> FakeAgent:
    """Build a FakeAgent with all dependencies mocked."""
    task_id = uuid4()
    trace_id = uuid4()

    if handle_task_return is None:
        handle_task_return = AgentResponse(
            task_id=task_id,
            trace_id=trace_id,
            agent_id="test-agent",
            payload={},
            status="success",
            output={"result": "test output"},
            tokens_used=100,
        )

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    # Mock execute for prompt reload check (returns None = no agent record)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_execute_result)

    agent = FakeAgent(
        role=AgentRole.ENGINEER,
        agent_id="test-agent",
        subscribe_topics=["agent.commands"],
        group_id="test-group",
        llm_agent=MagicMock(),
        db_session_factory=MagicMock(return_value=mock_session),
    )
    agent.handle_task_mock = AsyncMock(return_value=handle_task_return)
    return agent


def _make_command() -> AgentCommand:
    """Build a test AgentCommand."""
    return AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="ceo",
        payload={},
        target_role="engineer",
        instruction="Write a hello world function",
    )


# ─── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_skips_duplicate_message() -> None:
    """Duplicate message_id should be skipped without processing."""
    agent = _make_agent()
    command = _make_command()

    with (
        patch("nexus.agents.base.check_idempotency", new_callable=AsyncMock) as mock_idemp,
        patch("nexus.agents.base.publish", new_callable=AsyncMock),
        patch("nexus.agents.base.redis_pubsub", new_callable=AsyncMock),
    ):
        # First call: message is new
        mock_idemp.return_value = False  # NOT new → skip
        await agent._execute_with_guards(command)

        # handle_task should NOT have been called
        agent.handle_task_mock.assert_not_called()


@pytest.mark.asyncio
async def test_budget_exceeded_triggers_human_input() -> None:
    """When budget is exceeded, task should be escalated to human."""
    agent = _make_agent()
    command = _make_command()

    with (
        patch("nexus.agents.base.check_idempotency", new_callable=AsyncMock) as mock_idemp,
        patch("nexus.agents.base.check_daily_spend", new_callable=AsyncMock) as mock_daily,
        patch("nexus.agents.base.publish", new_callable=AsyncMock) as mock_publish,
        patch("nexus.agents.base.redis_pubsub", new_callable=AsyncMock),
    ):
        mock_idemp.return_value = True  # new message
        mock_daily.return_value = False  # budget exceeded!

        await agent._execute_with_guards(command)

        # handle_task should NOT have been called
        agent.handle_task_mock.assert_not_called()

        # Should have published to human.input_needed
        assert mock_publish.call_count >= 1
        published_topic = mock_publish.call_args_list[-1][0][0]
        assert published_topic == "human.input_needed"


@pytest.mark.asyncio
async def test_successful_execution_publishes_result() -> None:
    """Successful task should publish to agent.responses."""
    agent = _make_agent()
    command = _make_command()

    with (
        patch("nexus.agents.base.check_idempotency", new_callable=AsyncMock) as mock_idemp,
        patch("nexus.agents.base.check_daily_spend", new_callable=AsyncMock) as mock_daily,
        patch("nexus.agents.base.check_task_budget", new_callable=AsyncMock) as mock_task_budget,
        patch("nexus.agents.base.publish", new_callable=AsyncMock) as mock_publish,
        patch("nexus.agents.base.redis_pubsub", new_callable=AsyncMock),
        patch("nexus.agents.base.generate_embedding", new_callable=AsyncMock) as mock_embed,
        patch("nexus.agents.base.recall_similar", new_callable=AsyncMock) as mock_recall,
        patch("nexus.agents.base.get_working_memory", new_callable=AsyncMock) as mock_working,
        patch("nexus.agents.base.write_episode", new_callable=AsyncMock),
        patch("nexus.agents.base.clear_working_memory", new_callable=AsyncMock),
    ):
        mock_idemp.return_value = True
        mock_daily.return_value = True
        mock_task_budget.return_value = (True, 0)
        mock_embed.return_value = None
        mock_recall.return_value = []
        mock_working.return_value = {}

        await agent._execute_with_guards(command)

        # handle_task should have been called
        agent.handle_task_mock.assert_called_once()

        # Result should be published to agent.responses
        assert mock_publish.call_count >= 1
        published_topic = mock_publish.call_args_list[0][0][0]
        assert published_topic == "agent.responses"


@pytest.mark.asyncio
async def test_exception_in_handle_task_publishes_error() -> None:
    """Exception in handle_task should publish a failed response."""
    agent = _make_agent()
    agent.handle_task_mock = AsyncMock(side_effect=RuntimeError("test error"))
    command = _make_command()

    with (
        patch("nexus.agents.base.check_idempotency", new_callable=AsyncMock) as mock_idemp,
        patch("nexus.agents.base.check_daily_spend", new_callable=AsyncMock) as mock_daily,
        patch("nexus.agents.base.check_task_budget", new_callable=AsyncMock) as mock_task_budget,
        patch("nexus.agents.base.publish", new_callable=AsyncMock) as mock_publish,
        patch("nexus.agents.base.redis_pubsub", new_callable=AsyncMock),
        patch("nexus.agents.base.generate_embedding", new_callable=AsyncMock) as mock_embed,
        patch("nexus.agents.base.recall_similar", new_callable=AsyncMock) as mock_recall,
        patch("nexus.agents.base.get_working_memory", new_callable=AsyncMock) as mock_working,
    ):
        mock_idemp.return_value = True
        mock_daily.return_value = True
        mock_task_budget.return_value = (True, 0)
        mock_embed.return_value = None
        mock_recall.return_value = []
        mock_working.return_value = {}

        await agent._execute_with_guards(command)

        # Error response should be published
        assert mock_publish.call_count >= 1
        published_msg = mock_publish.call_args_list[0][0][1]
        assert published_msg.status == "failed"
        assert "test error" in (published_msg.error or "")


@pytest.mark.asyncio
async def test_message_filtering_by_role() -> None:
    """Messages targeting a different role should be ignored."""
    agent = _make_agent()
    command = _make_command()
    # Change target to a different role
    command.target_role = "analyst"

    with patch("nexus.agents.base.check_idempotency", new_callable=AsyncMock):
        await agent._process_message(command.model_dump(mode="json"))

    agent.handle_task_mock.assert_not_called()
