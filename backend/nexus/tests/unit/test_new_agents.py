"""Unit tests for Phase 2 agents: Analyst, Writer, QA."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.agents.analyst import AnalystAgent
from nexus.agents.qa import QAAgent
from nexus.agents.writer import WriterAgent
from nexus.db.models import AgentRole
from nexus.integrations.kafka.schemas import AgentCommand

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_session_factory() -> MagicMock:
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    return MagicMock(return_value=mock_session)


def _make_llm_agent(output: str = "Test output") -> MagicMock:
    mock_result = MagicMock()
    mock_result.output = output
    mock_usage = MagicMock()
    mock_usage.request_tokens = 100
    mock_usage.response_tokens = 50
    mock_result.usage.return_value = mock_usage

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)
    mock_agent.model = MagicMock()
    mock_agent.model.model_name = "test-model"
    return mock_agent


def _make_command(
    target_role: str = "analyst",
    instruction: str = "Research Python async patterns",
) -> AgentCommand:
    return AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="ceo",
        payload={},
        target_role=target_role,
        instruction=instruction,
    )


# ─── Analyst Agent Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("nexus.agents.analyst.record_usage", new_callable=AsyncMock)
async def test_analyst_handle_task_returns_success(mock_usage: AsyncMock) -> None:
    """AnalystAgent should return success with LLM output."""
    agent = AnalystAgent(
        role=AgentRole.ANALYST,
        agent_id="analyst-1",
        subscribe_topics=["agent.commands"],
        group_id="nexus-analyst",
        llm_agent=_make_llm_agent("Research findings here"),
        db_session_factory=_make_session_factory(),
    )

    command = _make_command(target_role="analyst", instruction="Research X")
    session = AsyncMock()
    response = await agent.handle_task(command, session)

    assert response.status == "success"
    assert response.output is not None
    assert response.output["result"] == "Research findings here"
    assert response.tokens_used == 150


@pytest.mark.asyncio
@patch("nexus.agents.analyst.record_usage", new_callable=AsyncMock)
async def test_analyst_includes_memory_context(mock_usage: AsyncMock) -> None:
    """AnalystAgent should include memory context in the prompt."""
    llm_agent = _make_llm_agent()
    agent = AnalystAgent(
        role=AgentRole.ANALYST,
        agent_id="analyst-1",
        subscribe_topics=["agent.commands"],
        group_id="nexus-analyst",
        llm_agent=llm_agent,
        db_session_factory=_make_session_factory(),
    )
    agent._memory_context = {
        "similar_episodes": ["Past research on topic Y"],
        "working_memory": {"key": "value"},
    }

    command = _make_command()
    session = AsyncMock()
    await agent.handle_task(command, session)

    # Check that the LLM was called with context included
    call_args = llm_agent.run.call_args[0][0]
    assert "Past research on topic Y" in call_args
    assert "Working memory" in call_args


# ─── Writer Agent Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("nexus.agents.writer.record_usage", new_callable=AsyncMock)
async def test_writer_handle_task_returns_success(mock_usage: AsyncMock) -> None:
    """WriterAgent should return success with LLM output."""
    agent = WriterAgent(
        role=AgentRole.WRITER,
        agent_id="writer-1",
        subscribe_topics=["agent.commands"],
        group_id="nexus-writer",
        llm_agent=_make_llm_agent("Draft email content"),
        db_session_factory=_make_session_factory(),
    )

    command = _make_command(target_role="writer", instruction="Write an email")
    session = AsyncMock()
    response = await agent.handle_task(command, session)

    assert response.status == "success"
    assert response.output is not None
    assert response.output["result"] == "Draft email content"


# ─── QA Agent Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("nexus.agents.qa.publish", new_callable=AsyncMock)
@patch("nexus.agents.qa.record_usage", new_callable=AsyncMock)
async def test_qa_approves_good_output(mock_usage: AsyncMock, mock_publish: AsyncMock) -> None:
    """QA should approve and publish TaskResult when output is approved."""
    qa_response = '{"approved": true, "score": 0.9, "feedback": "Good work", "issues": []}'
    agent = QAAgent(
        role=AgentRole.QA,
        agent_id="qa-1",
        subscribe_topics=["task.review_queue"],
        group_id="nexus-qa",
        llm_agent=_make_llm_agent(qa_response),
        db_session_factory=_make_session_factory(),
    )

    command = _make_command(target_role="qa", instruction="Review this output")
    command.payload = {"aggregated_output": "Some output to review"}
    session = AsyncMock()
    response = await agent.handle_task(command, session)

    assert response.status == "success"
    assert response.output is not None
    assert response.output["approved"] is True
    # Should publish to task.results
    mock_publish.assert_called()


@pytest.mark.asyncio
@patch("nexus.agents.qa.publish", new_callable=AsyncMock)
@patch("nexus.agents.qa.record_usage", new_callable=AsyncMock)
async def test_qa_rejects_bad_output(mock_usage: AsyncMock, mock_publish: AsyncMock) -> None:
    """QA should reject and publish rework command when output is rejected."""
    qa_response = (
        '{"approved": false, "score": 0.3, "feedback": "Missing sources",'
        ' "issues": ["No citations"]}'
    )
    agent = QAAgent(
        role=AgentRole.QA,
        agent_id="qa-1",
        subscribe_topics=["task.review_queue"],
        group_id="nexus-qa",
        llm_agent=_make_llm_agent(qa_response),
        db_session_factory=_make_session_factory(),
    )

    command = _make_command(target_role="qa", instruction="Review this output")
    command.payload = {
        "aggregated_output": "Bad output",
        "original_role": "analyst",
        "original_instruction": "Research X",
    }
    session = AsyncMock()
    response = await agent.handle_task(command, session)

    assert response.status == "success"
    assert response.output is not None
    assert response.output["approved"] is False
    # Should publish rework command to agent.commands
    mock_publish.assert_called()


@pytest.mark.asyncio
@patch("nexus.agents.qa.publish", new_callable=AsyncMock)
@patch("nexus.agents.qa.record_usage", new_callable=AsyncMock)
async def test_qa_handles_non_json_response(mock_usage: AsyncMock, mock_publish: AsyncMock) -> None:
    """QA should default to approved when LLM returns non-JSON output."""
    agent = QAAgent(
        role=AgentRole.QA,
        agent_id="qa-1",
        subscribe_topics=["task.review_queue"],
        group_id="nexus-qa",
        llm_agent=_make_llm_agent("Looks good to me!"),
        db_session_factory=_make_session_factory(),
    )

    command = _make_command(target_role="qa", instruction="Review this")
    command.payload = {"aggregated_output": "Output"}
    session = AsyncMock()
    response = await agent.handle_task(command, session)

    assert response.output is not None
    assert response.output["approved"] is True
