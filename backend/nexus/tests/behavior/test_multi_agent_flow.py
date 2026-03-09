"""Behavior tests for multi-agent orchestration flow.

Tests the full CEO → Specialist → CEO Aggregation → QA pipeline
with mocked LLM responses and real Kafka/Redis interactions mocked.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.agents.ceo import CEOAgent
from nexus.agents.qa import QAAgent
from nexus.db.models import AgentRole
from nexus.kafka.schemas import AgentCommand


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    def add_side_effect(obj: object) -> None:
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid4()

    session.add = MagicMock(side_effect=add_side_effect)
    return session


def _mock_llm(output: str) -> MagicMock:
    result = MagicMock()
    result.output = output
    usage = MagicMock()
    usage.request_tokens = 100
    usage.response_tokens = 50
    result.usage.return_value = usage

    agent = MagicMock()
    agent.run = AsyncMock(return_value=result)
    agent.model = MagicMock()
    agent.model.model_name = "test-model"
    return agent


# ─── Behavior: Full Decomposition Flow ───────────────────────────────────────


@pytest.mark.asyncio
@patch("nexus.agents.ceo.publish", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.record_usage", new_callable=AsyncMock)
async def test_ceo_decomposes_research_and_email_task(
    mock_usage: AsyncMock,
    mock_wm: AsyncMock,
    mock_publish: AsyncMock,
) -> None:
    """CEO should decompose 'research + email' into analyst + writer subtasks."""
    decomposition = json.dumps([
        {"role": "analyst", "instruction": "Research the market for AI tools", "depends_on": []},
        {"role": "writer", "instruction": "Draft an email summarizing the research", "depends_on": [0]},
    ])

    ceo = CEOAgent(
        role=AgentRole.CEO,
        agent_id="ceo-test",
        subscribe_topics=["task.queue"],
        group_id="nexus-ceo",
        llm_agent=_mock_llm(decomposition),
        db_session_factory=MagicMock(return_value=_mock_session()),
    )

    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="api",
        payload={},
        target_role="ceo",
        instruction="Research the AI tools market and draft a summary email",
    )

    session = _mock_session()
    response = await ceo.handle_task(command, session)

    # CEO should decompose into 2 subtasks
    assert response.output is not None
    assert response.output["action"] == "decomposed"
    assert response.output["subtask_count"] == 2

    # Only the analyst subtask should be dispatched (writer depends on analyst)
    publish_calls = mock_publish.call_args_list
    dispatched_topics = [call[0][0] for call in publish_calls]
    assert "agent.commands" in dispatched_topics


# ─── Behavior: QA Review Pipeline ────────────────────────────────────────────


@pytest.mark.asyncio
@patch("nexus.agents.qa.publish", new_callable=AsyncMock)
@patch("nexus.agents.qa.record_usage", new_callable=AsyncMock)
async def test_qa_approves_and_publishes_final_result(
    mock_usage: AsyncMock,
    mock_publish: AsyncMock,
) -> None:
    """QA should approve good output and publish to task.results."""
    qa_review = json.dumps({
        "approved": True,
        "score": 0.85,
        "feedback": "Well-researched and clearly written",
        "issues": [],
    })

    qa = QAAgent(
        role=AgentRole.QA,
        agent_id="qa-test",
        subscribe_topics=["task.review_queue"],
        group_id="nexus-qa",
        llm_agent=_mock_llm(qa_review),
        db_session_factory=MagicMock(return_value=_mock_session()),
    )

    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="ceo-test",
        payload={
            "aggregated_output": "Research findings + email draft",
            "original_instruction": "Research AI tools and draft email",
        },
        target_role="qa",
        instruction="Review the aggregated output",
    )

    session = _mock_session()
    response = await qa.handle_task(command, session)

    assert response.output is not None
    assert response.output["approved"] is True

    # Should publish to task.results
    publish_calls = mock_publish.call_args_list
    published_topics = [call[0][0] for call in publish_calls]
    assert "task.results" in published_topics


@pytest.mark.asyncio
@patch("nexus.agents.qa.publish", new_callable=AsyncMock)
@patch("nexus.agents.qa.record_usage", new_callable=AsyncMock)
async def test_qa_rejects_and_requests_rework(
    mock_usage: AsyncMock,
    mock_publish: AsyncMock,
) -> None:
    """QA should reject bad output and route back for rework."""
    qa_review = json.dumps({
        "approved": False,
        "score": 0.4,
        "feedback": "Missing citations and incomplete analysis",
        "issues": ["No sources cited", "Only covers 2 of 5 competitors"],
    })

    qa = QAAgent(
        role=AgentRole.QA,
        agent_id="qa-test",
        subscribe_topics=["task.review_queue"],
        group_id="nexus-qa",
        llm_agent=_mock_llm(qa_review),
        db_session_factory=MagicMock(return_value=_mock_session()),
    )

    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="ceo-test",
        payload={
            "aggregated_output": "Incomplete research",
            "original_role": "analyst",
            "original_instruction": "Research AI tools market",
        },
        target_role="qa",
        instruction="Review the output",
    )

    session = _mock_session()
    response = await qa.handle_task(command, session)

    assert response.output is not None
    assert response.output["approved"] is False

    # Should publish rework command to agent.commands
    publish_calls = mock_publish.call_args_list
    published_topics = [call[0][0] for call in publish_calls]
    assert "agent.commands" in published_topics


# ─── Behavior: Aggregation with Dependencies ─────────────────────────────────


@pytest.mark.asyncio
@patch("nexus.agents.ceo.publish", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.get_working_memory", new_callable=AsyncMock)
async def test_ceo_dispatches_dependent_subtask_after_dependency_completes(
    mock_get_wm: AsyncMock,
    mock_set_wm: AsyncMock,
    mock_publish: AsyncMock,
) -> None:
    """When subtask 0 completes, CEO should dispatch subtask 1 that depends on it."""
    subtask_0_id = str(uuid4())
    subtask_1_id = str(uuid4())
    parent_task_id = str(uuid4())

    mock_get_wm.return_value = {
        "parent_task_id": parent_task_id,
        "original_instruction": "Research and write",
        "subtasks": {
            subtask_0_id: {
                "role": "analyst",
                "instruction": "Research X",
                "depends_on": [],
                "status": "dispatched",
                "output": None,
            },
            subtask_1_id: {
                "role": "writer",
                "instruction": "Write email based on research",
                "depends_on": [subtask_0_id],
                "status": "pending",
                "output": None,
            },
        },
        "total": 2,
        "completed": 0,
    }

    ceo = CEOAgent(
        role=AgentRole.CEO,
        agent_id="ceo-test",
        subscribe_topics=["task.queue"],
        group_id="nexus-ceo",
        llm_agent=_mock_llm(""),
        db_session_factory=MagicMock(return_value=_mock_session()),
    )

    # Simulate subtask 0 completing
    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="result-consumer",
        payload={
            "_response_aggregation": True,
            "subtask_id": subtask_0_id,
            "parent_task_id": parent_task_id,
            "subtask_output": "Research findings: X has 60% market share",
            "subtask_status": "success",
        },
        target_role="ceo",
        instruction="Subtask completed",
    )

    session = _mock_session()
    response = await ceo.handle_task(command, session)

    # Should dispatch subtask 1 since its dependency (subtask 0) is now complete
    assert response.status == "success"
    # Subtask 1 should now be dispatched (publish called for agent.commands)
    publish_calls = mock_publish.call_args_list
    assert len(publish_calls) >= 1
