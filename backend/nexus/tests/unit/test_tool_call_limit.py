"""Unit tests for tool call limit enforcement."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.agents.base import AgentBase, ToolCallLimitExceededError
from nexus.agents.factory import _wrap_tools_with_counter
from nexus.db.models import AgentRole
from nexus.kafka.schemas import AgentCommand, AgentResponse

# ─── Tool wrapping tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_counter_increments_on_each_call() -> None:
    """Each wrapped tool call should increment the counter."""
    counter = {"count": 0, "limit": 20}

    async def dummy_tool() -> str:
        return "ok"

    wrapped = _wrap_tools_with_counter([dummy_tool], counter)
    assert len(wrapped) == 1

    await wrapped[0]()
    assert counter["count"] == 1

    await wrapped[0]()
    assert counter["count"] == 2


@pytest.mark.asyncio
async def test_raises_at_limit() -> None:
    """Counter should raise ToolCallLimitExceededError when limit is exceeded."""
    counter = {"count": 0, "limit": 3}

    async def dummy_tool() -> str:
        return "ok"

    wrapped = _wrap_tools_with_counter([dummy_tool], counter)

    # Calls 1-3 should succeed
    for _ in range(3):
        await wrapped[0]()

    # Call 4 should raise
    with pytest.raises(ToolCallLimitExceededError, match="3"):
        await wrapped[0]()


@pytest.mark.asyncio
async def test_multiple_tools_share_counter() -> None:
    """Multiple wrapped tools should share the same counter."""
    counter = {"count": 0, "limit": 5}

    async def tool_a() -> str:
        return "a"

    async def tool_b() -> str:
        return "b"

    wrapped = _wrap_tools_with_counter([tool_a, tool_b], counter)

    await wrapped[0]()  # tool_a: count=1
    await wrapped[1]()  # tool_b: count=2
    await wrapped[0]()  # tool_a: count=3

    assert counter["count"] == 3


@pytest.mark.asyncio
async def test_tool_args_pass_through() -> None:
    """Wrapped tools should pass through arguments correctly."""
    counter = {"count": 0, "limit": 20}

    async def tool_with_args(x: int, y: str = "default") -> str:
        return f"{x}-{y}"

    wrapped = _wrap_tools_with_counter([tool_with_args], counter)
    result = await wrapped[0](42, y="custom")
    assert result == "42-custom"


def test_empty_tools_list() -> None:
    """Empty tools list should return empty wrapped list."""
    counter = {"count": 0, "limit": 20}
    wrapped = _wrap_tools_with_counter([], counter)
    assert wrapped == []


# ─── Counter reset between tasks ─────────────────────────────────────────────


class FakeAgent(AgentBase):
    """Minimal concrete agent for testing."""

    handle_task_mock: AsyncMock

    async def handle_task(self, message, session):
        return await self.handle_task_mock(message, session)


def _make_agent() -> FakeAgent:
    task_id = uuid4()
    trace_id = uuid4()

    response = AgentResponse(
        task_id=task_id,
        trace_id=trace_id,
        agent_id="test-agent",
        payload={},
        status="success",
        output={"result": "test"},
        tokens_used=100,
    )

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    agent = FakeAgent(
        role=AgentRole.ENGINEER,
        agent_id="test-agent",
        subscribe_topics=["agent.commands"],
        group_id="test-group",
        llm_agent=MagicMock(),
        db_session_factory=MagicMock(return_value=mock_session),
    )
    agent.handle_task_mock = AsyncMock(return_value=response)
    agent._tool_call_counter = {"count": 15, "limit": 20}
    return agent


@pytest.mark.asyncio
async def test_counter_resets_between_tasks() -> None:
    """Tool call counter should reset to 0 at start of each task."""
    agent = _make_agent()
    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="ceo",
        payload={},
        target_role="engineer",
        instruction="Test task",
    )

    with (
        patch("nexus.agents.base.check_idempotency", new_callable=AsyncMock) as mock_idemp,
        patch("nexus.agents.base.check_daily_spend", new_callable=AsyncMock) as mock_daily,
        patch("nexus.agents.base.check_task_budget", new_callable=AsyncMock) as mock_task_budget,
        patch("nexus.agents.base.publish", new_callable=AsyncMock),
        patch("nexus.agents.base.redis_pubsub", new_callable=AsyncMock),
        patch("nexus.agents.base.generate_embedding", new_callable=AsyncMock, return_value=None),
        patch("nexus.agents.base.recall_similar", new_callable=AsyncMock, return_value=[]),
        patch("nexus.agents.base.get_working_memory", new_callable=AsyncMock, return_value={}),
        patch("nexus.agents.base.write_episode", new_callable=AsyncMock),
        patch("nexus.agents.base.clear_working_memory", new_callable=AsyncMock),
    ):
        mock_idemp.return_value = True
        mock_daily.return_value = True
        mock_task_budget.return_value = (True, 0)

        # Counter starts at 15 from construction
        assert agent._tool_call_counter["count"] == 15

        await agent._execute_with_guards(command)

        # Counter should have been reset to 0 at the start
        assert agent._tool_call_counter["count"] == 0


@pytest.mark.asyncio
async def test_tool_call_limit_triggers_human_input() -> None:
    """ToolCallLimitExceededError should escalate to human.input_needed."""
    agent = _make_agent()
    agent.handle_task_mock = AsyncMock(
        side_effect=ToolCallLimitExceededError("Tool call limit (20) exceeded")
    )
    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="ceo",
        payload={},
        target_role="engineer",
        instruction="Test task",
    )

    with (
        patch("nexus.agents.base.check_idempotency", new_callable=AsyncMock) as mock_idemp,
        patch("nexus.agents.base.check_daily_spend", new_callable=AsyncMock) as mock_daily,
        patch("nexus.agents.base.check_task_budget", new_callable=AsyncMock) as mock_task_budget,
        patch("nexus.agents.base.publish", new_callable=AsyncMock) as mock_publish,
        patch("nexus.agents.base.redis_pubsub", new_callable=AsyncMock),
        patch("nexus.agents.base.generate_embedding", new_callable=AsyncMock, return_value=None),
        patch("nexus.agents.base.recall_similar", new_callable=AsyncMock, return_value=[]),
        patch("nexus.agents.base.get_working_memory", new_callable=AsyncMock, return_value={}),
    ):
        mock_idemp.return_value = True
        mock_daily.return_value = True
        mock_task_budget.return_value = (True, 0)

        await agent._execute_with_guards(command)

        # Should have published to human.input_needed
        publish_calls = [
            call for call in mock_publish.call_args_list if call[0][0] == "human.input_needed"
        ]
        assert len(publish_calls) == 1
