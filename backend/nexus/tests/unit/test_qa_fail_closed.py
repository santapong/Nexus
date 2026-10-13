"""Malformed legacy QA and optional review failures never authorize completion."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.agents.qa import QAAgent
from nexus.core.kafka.schemas import AgentCommand
from nexus.core.kafka.topics import Topics
from nexus.db.models import AgentRole
from nexus.integrations.temporal.activities import qa_review_activity
from nexus.integrations.temporal.schemas import ReviewInput

INVALID = [
    "Looks good",
    "",
    "{}",
    "[]",
    "null",
    '{"score":0.9}',
    '{"approved":"false"}',
    '{"approved":"true"}',
    '{"approved":1}',
    '{"approved":null}',
    '{"approved":false,"approved":true}',
]


@pytest.mark.parametrize("raw", INVALID)
async def test_invalid_qa_cannot_publish_success_or_completion(raw: str) -> None:
    agent = QAAgent(
        role=AgentRole.QA,
        agent_id="offline-qa",
        subscribe_topics=[],
        group_id="fixture",
        llm_agent=MagicMock(),
        db_session_factory=MagicMock(),
    )
    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="manager",
        target_role="qa",
        instruction="Synthetic review",
        payload={"aggregated_output": "original evidence"},
    )
    with (
        patch.object(
            agent,
            "_run_with_retry",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    output=raw,
                    usage=SimpleNamespace(input_tokens=11, output_tokens=5),
                )
            ),
        ),
        patch("nexus.agents.qa.record_usage", new_callable=AsyncMock),
        patch("nexus.agents.qa.publish", new_callable=AsyncMock) as publish,
    ):
        response = await agent.handle_task(command, AsyncMock())
    assert response.status == "failed"
    assert response.output is not None
    assert response.output["approved"] is False
    assert response.output["verdict"] == "inconclusive"
    assert response.output["qa_review"] == raw
    assert not any(call.args[0] == Topics.TASK_RESULTS for call in publish.call_args_list)
    assert not any(call.args[0] == Topics.AGENT_COMMANDS for call in publish.call_args_list)


@pytest.mark.parametrize("raw", ['{"approved":true}', '```json\n{"approved":true}\n```'])
async def test_explicit_boolean_approval_keeps_the_existing_review_contract(raw: str) -> None:
    agent = QAAgent(
        role=AgentRole.QA,
        agent_id="offline-qa",
        subscribe_topics=[],
        group_id="fixture",
        llm_agent=MagicMock(),
        db_session_factory=MagicMock(),
    )
    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="manager",
        target_role="qa",
        instruction="Synthetic review",
        payload={},
    )
    with (
        patch.object(
            agent,
            "_run_with_retry",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    output=raw,
                    usage=SimpleNamespace(input_tokens=11, output_tokens=5),
                )
            ),
        ),
        patch("nexus.agents.qa.record_usage", new_callable=AsyncMock),
        patch("nexus.agents.qa.publish", new_callable=AsyncMock) as publish,
    ):
        response = await agent.handle_task(command, AsyncMock())
    assert response.output is not None and response.output["approved"] is True
    assert any(call.args[0] == Topics.TASK_RESULTS for call in publish.call_args_list)


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"feedback": "Seems fine"},
        {"approved": "false"},
        {"approved": 1},
        {"status": "failed", "approved": True},
        {"output": "{}"},
        {"output": {"qa_review": "malformed"}},
        {"approved": True, "output": {"qa_review": '{"approved":false}'}},
    ],
)
async def test_temporal_missing_malformed_or_failed_review_cannot_approve(result: object) -> None:
    review = ReviewInput(task_id=str(uuid4()), trace_id=str(uuid4()), output="original evidence")
    with (
        patch("nexus.core.kafka.producer.publish", new_callable=AsyncMock),
        patch(
            "nexus.integrations.temporal.activities._poll_task_completion",
            new=AsyncMock(return_value=result),
        ),
    ):
        output = await qa_review_activity(review)
    assert output.approved is False
    assert output.final_output == "original evidence"
    assert output.feedback


@pytest.mark.parametrize("failure", [TimeoutError("review timeout"), RuntimeError("review failed")])
async def test_temporal_review_error_cannot_auto_approve(failure: Exception) -> None:
    review = ReviewInput(task_id=str(uuid4()), trace_id=str(uuid4()), output="original evidence")
    with (
        patch("nexus.core.kafka.producer.publish", new_callable=AsyncMock),
        patch(
            "nexus.integrations.temporal.activities._poll_task_completion",
            new=AsyncMock(side_effect=failure),
        ),
    ):
        output = await qa_review_activity(review)
    assert output.approved is False
    assert output.final_output == "original evidence"


@pytest.mark.parametrize("approved", [True, False])
async def test_temporal_consumes_explicit_nested_qa_evidence(approved: bool) -> None:
    review = ReviewInput(task_id=str(uuid4()), trace_id=str(uuid4()), output="original evidence")
    polled = {
        "status": "completed",
        "output": json.dumps(
            {"qa_review": json.dumps({"approved": approved, "feedback": "fixture"})}
        ),
    }
    with (
        patch("nexus.core.kafka.producer.publish", new_callable=AsyncMock),
        patch(
            "nexus.integrations.temporal.activities._poll_task_completion",
            new=AsyncMock(return_value=polled),
        ),
    ):
        output = await qa_review_activity(review)
    assert output.approved is approved
    assert output.feedback == "fixture"
