"""Unit tests for CEO task decomposition and multi-agent orchestration."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.agents.ceo import CEOAgent
from nexus.db.models import AgentRole
from nexus.kafka.schemas import AgentCommand, AgentResponse


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_session_factory() -> MagicMock:
    mock_session = _make_mock_session()
    return MagicMock(return_value=mock_session)


def _make_mock_session() -> AsyncMock:
    """Create a properly mocked async DB session that assigns UUIDs on add()."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()

    # Mock task creation — give each task a unique ID
    def add_side_effect(obj: object) -> None:
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid4()

    mock_session.add = MagicMock(side_effect=add_side_effect)
    return mock_session


def _make_llm_agent(decomposition: list[dict] | str = "") -> MagicMock:
    if isinstance(decomposition, list):
        output = json.dumps(decomposition)
    else:
        output = decomposition

    mock_result = MagicMock()
    mock_result.output = output
    mock_usage = MagicMock()
    mock_usage.request_tokens = 200
    mock_usage.response_tokens = 100
    mock_result.usage.return_value = mock_usage

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)
    mock_agent.model = MagicMock()
    mock_agent.model.model_name = "test-model"
    return mock_agent


def _make_ceo(decomposition: list[dict] | str = "") -> CEOAgent:
    return CEOAgent(
        role=AgentRole.CEO,
        agent_id="ceo-1",
        subscribe_topics=["task.queue", "agent.responses"],
        group_id="nexus-ceo",
        llm_agent=_make_llm_agent(decomposition),
        db_session_factory=_make_session_factory(),
    )


def _make_command(instruction: str = "Research X and write an email") -> AgentCommand:
    return AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="api",
        payload={},
        target_role="ceo",
        instruction=instruction,
    )


# ─── Decomposition Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("nexus.agents.ceo.publish", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.record_usage", new_callable=AsyncMock)
async def test_ceo_decomposes_multi_agent_task(
    mock_usage: AsyncMock,
    mock_wm: AsyncMock,
    mock_publish: AsyncMock,
) -> None:
    """CEO should decompose a task into multiple subtasks and dispatch them."""
    decomposition = [
        {"role": "analyst", "instruction": "Research competitors", "depends_on": []},
        {"role": "writer", "instruction": "Draft email summary", "depends_on": [0]},
    ]
    ceo = _make_ceo(decomposition)
    command = _make_command("Research competitors and draft email")
    session = _make_mock_session()

    response = await ceo.handle_task(command, session)

    assert response.status == "success"
    assert response.output is not None
    assert response.output["action"] == "decomposed"
    assert response.output["subtask_count"] == 2
    # Should dispatch the first subtask (no dependencies)
    mock_publish.assert_called()


@pytest.mark.asyncio
@patch("nexus.agents.ceo.publish", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.record_usage", new_callable=AsyncMock)
async def test_ceo_single_agent_task(
    mock_usage: AsyncMock,
    mock_wm: AsyncMock,
    mock_publish: AsyncMock,
) -> None:
    """CEO should handle single-agent tasks with a single-item decomposition."""
    decomposition = [
        {"role": "engineer", "instruction": "Write a hello world function", "depends_on": []},
    ]
    ceo = _make_ceo(decomposition)
    command = _make_command("Write a hello world function")
    session = _make_mock_session()

    response = await ceo.handle_task(command, session)

    assert response.output is not None
    assert response.output["subtask_count"] == 1


@pytest.mark.asyncio
@patch("nexus.agents.ceo.publish", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.record_usage", new_callable=AsyncMock)
async def test_ceo_fallback_on_invalid_decomposition(
    mock_usage: AsyncMock,
    mock_wm: AsyncMock,
    mock_publish: AsyncMock,
) -> None:
    """CEO should fall back to engineer when LLM returns invalid JSON."""
    ceo = _make_ceo("This is not valid JSON")
    command = _make_command("Do something")
    session = _make_mock_session()

    response = await ceo.handle_task(command, session)

    assert response.output is not None
    assert response.output["action"] == "decomposed"
    assert response.output["subtask_count"] == 1  # fallback to engineer


@pytest.mark.asyncio
@patch("nexus.agents.ceo.publish", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.record_usage", new_callable=AsyncMock)
async def test_ceo_validates_roles(
    mock_usage: AsyncMock,
    mock_wm: AsyncMock,
    mock_publish: AsyncMock,
) -> None:
    """CEO should normalize invalid roles to 'engineer'."""
    decomposition = [
        {"role": "invalid_role", "instruction": "Do thing", "depends_on": []},
    ]
    ceo = _make_ceo(decomposition)
    command = _make_command()
    session = _make_mock_session()

    response = await ceo.handle_task(command, session)

    assert response.output is not None
    assert response.output["subtask_count"] == 1


# ─── Aggregation Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("nexus.agents.ceo.publish", new_callable=AsyncMock)
@patch("nexus.agents.ceo.set_working_memory", new_callable=AsyncMock)
@patch("nexus.agents.ceo.get_working_memory", new_callable=AsyncMock)
async def test_ceo_aggregates_when_all_complete(
    mock_get_wm: AsyncMock,
    mock_set_wm: AsyncMock,
    mock_publish: AsyncMock,
) -> None:
    """CEO should aggregate and route to QA when all subtasks complete."""
    subtask_id = str(uuid4())
    parent_task_id = str(uuid4())

    mock_get_wm.return_value = {
        "parent_task_id": parent_task_id,
        "original_instruction": "Research and write email",
        "subtasks": {
            subtask_id: {
                "role": "analyst",
                "instruction": "Research X",
                "depends_on": [],
                "status": "pending",
                "output": None,
            },
        },
        "total": 1,
        "completed": 0,
    }

    ceo = _make_ceo()
    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="result-consumer",
        payload={
            "_response_aggregation": True,
            "subtask_id": subtask_id,
            "parent_task_id": parent_task_id,
            "subtask_output": "Research results here",
            "subtask_status": "success",
        },
        target_role="ceo",
        instruction="Subtask completed",
    )

    session = AsyncMock()
    response = await ceo.handle_task(command, session)

    assert response.status == "success"
    assert response.output is not None
    assert response.output["action"] == "aggregated_and_sent_to_qa"
    # Should publish to task.review_queue
    mock_publish.assert_called()
