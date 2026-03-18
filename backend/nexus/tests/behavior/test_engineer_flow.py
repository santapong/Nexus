"""Behavior tests for the Engineer agent flow.

Tests the full flow with mocked LLM — verifies agent decision logic,
not LLM output quality.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.agents.engineer import EngineerAgent
from nexus.db.models import AgentRole
from nexus.integrations.kafka.schemas import AgentCommand


def _make_engineer() -> EngineerAgent:
    """Build an EngineerAgent with all dependencies mocked."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()

    # Mock Pydantic AI Agent
    mock_llm = MagicMock()
    mock_result = MagicMock()
    mock_result.output = "def hello():\n    return 'Hello, World!'"
    mock_usage = MagicMock()
    mock_usage.request_tokens = 500
    mock_usage.response_tokens = 200
    mock_result.usage.return_value = mock_usage
    mock_llm.run = AsyncMock(return_value=mock_result)

    agent = EngineerAgent(
        role=AgentRole.ENGINEER,
        agent_id="test-engineer",
        subscribe_topics=["agent.commands"],
        group_id="test-engineer-group",
        llm_agent=mock_llm,
        db_session_factory=MagicMock(return_value=mock_session),
    )
    return agent


def _make_command(instruction: str = "Write a hello world function") -> AgentCommand:
    return AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="ceo",
        payload={},
        target_role="engineer",
        instruction=instruction,
    )


@pytest.mark.asyncio
async def test_engineer_returns_success_response() -> None:
    """Engineer should return a success response with LLM output."""
    agent = _make_engineer()
    command = _make_command()
    mock_session = AsyncMock()

    with patch("nexus.agents.engineer.record_usage", new_callable=AsyncMock):
        response = await agent.handle_task(command, mock_session)

    assert response.status == "success"
    assert response.output is not None
    assert "result" in response.output
    assert response.tokens_used == 700  # 500 + 200


@pytest.mark.asyncio
async def test_engineer_records_token_usage() -> None:
    """Engineer should record token usage after LLM call."""
    agent = _make_engineer()
    command = _make_command()
    mock_session = AsyncMock()

    with patch("nexus.agents.engineer.record_usage", new_callable=AsyncMock) as mock_record:
        await agent.handle_task(command, mock_session)

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args[1]
    assert call_kwargs["input_tokens"] == 500
    assert call_kwargs["output_tokens"] == 200


@pytest.mark.asyncio
async def test_engineer_includes_memory_context() -> None:
    """Engineer should include memory context in the LLM prompt."""
    agent = _make_engineer()
    agent._memory_context = {
        "similar_episodes": ["Fixed a similar bug in auth module"],
        "working_memory": {},
    }
    command = _make_command()
    mock_session = AsyncMock()

    with patch("nexus.agents.engineer.record_usage", new_callable=AsyncMock):
        await agent.handle_task(command, mock_session)

    # Verify the LLM was called with context-enriched message
    call_args = agent.llm_agent.run.call_args[0][0]
    assert "past experience" in call_args.lower() or "similar" in call_args.lower()
