"""Behavior tests for the task result consumer.

Tests that agent.responses messages correctly update task status in DB,
publish to task.results, and broadcast via Redis pub/sub.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.core.kafka.result_consumer import _handle_response, _map_status


def _make_response_raw(
    *,
    status: str = "success",
    output: dict[str, Any] | None = None,
    error: str | None = None,
    tokens_used: int = 500,
    action: str | None = None,
) -> dict[str, Any]:
    """Build a raw dict mimicking an AgentResponse Kafka message."""
    task_id = uuid4()
    trace_id = uuid4()
    message_id = uuid4()
    out = output or ({"result": "print('hello')"} if action is None else {"action": action})
    return {
        "message_id": str(message_id),
        "task_id": str(task_id),
        "trace_id": str(trace_id),
        "agent_id": "test-engineer",
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": {},
        "status": status,
        "output": out,
        "error": error,
        "tokens_used": tokens_used,
    }


# ─── Status mapping ───────────────────────────────────────────────────────────


def test_map_status_success() -> None:
    assert _map_status("success") == "completed"


def test_map_status_failed() -> None:
    assert _map_status("failed") == "failed"


def test_map_status_escalated() -> None:
    assert _map_status("escalated") == "escalated"


def test_map_status_unknown_defaults_to_completed() -> None:
    assert _map_status("unexpected_value") == "completed"


# ─── Full handler behavior ────────────────────────────────────────────────────


def _make_session_factory(mock_task: MagicMock) -> MagicMock:
    """Build a mock session factory that returns an async context manager."""
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_task))
    )

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=cm)


@pytest.mark.asyncio
async def test_handle_response_updates_task_to_completed() -> None:
    """Successful response should update task status to 'completed' in DB."""
    raw = _make_response_raw(status="success", tokens_used=700)
    mock_task = MagicMock()
    mock_task.parent_task_id = str(uuid4())
    mock_task.assigned_agent_id = "test-engineer"
    mock_session_factory = _make_session_factory(mock_task)

    with (
        patch(
            "nexus.kafka.result_consumer.check_idempotency",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("nexus.kafka.result_consumer.publish", new_callable=AsyncMock),
        patch("nexus.kafka.result_consumer.redis_pubsub", new_callable=AsyncMock),
    ):
        await _handle_response(raw, mock_session_factory)

    assert mock_task.status == "completed"
    assert mock_task.tokens_used == 700
    assert mock_task.completed_at is not None


@pytest.mark.asyncio
async def test_handle_response_updates_task_to_failed() -> None:
    """Failed response should update task status to 'failed' in DB."""
    raw = _make_response_raw(status="failed", error="Tool execution timed out")
    mock_task = MagicMock()
    mock_task.parent_task_id = str(uuid4())
    mock_task.assigned_agent_id = "test-engineer"
    mock_session_factory = _make_session_factory(mock_task)

    with (
        patch(
            "nexus.kafka.result_consumer.check_idempotency",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("nexus.kafka.result_consumer.publish", new_callable=AsyncMock),
        patch("nexus.kafka.result_consumer.redis_pubsub", new_callable=AsyncMock),
    ):
        await _handle_response(raw, mock_session_factory)

    assert mock_task.status == "failed"
    assert mock_task.error == "Tool execution timed out"


@pytest.mark.asyncio
async def test_handle_response_skips_duplicate_messages() -> None:
    """Duplicate message_id should be skipped — idempotency enforced."""
    raw = _make_response_raw()
    mock_session_factory = MagicMock()

    with (
        patch(
            "nexus.kafka.result_consumer.check_idempotency",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("nexus.kafka.result_consumer.publish", new_callable=AsyncMock) as mock_publish,
    ):
        await _handle_response(raw, mock_session_factory)

    # No DB update, no publish
    mock_session_factory.assert_not_called()
    mock_publish.assert_not_called()


@pytest.mark.asyncio
async def test_handle_response_skips_ceo_delegation() -> None:
    """CEO delegation responses should be ignored — no task update."""
    raw = _make_response_raw(action="delegated_to_engineer")
    mock_session_factory = MagicMock()

    with (
        patch(
            "nexus.kafka.result_consumer.check_idempotency",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("nexus.kafka.result_consumer.publish", new_callable=AsyncMock) as mock_publish,
    ):
        await _handle_response(raw, mock_session_factory)

    mock_session_factory.assert_not_called()
    mock_publish.assert_not_called()


@pytest.mark.asyncio
async def test_handle_response_publishes_task_result() -> None:
    """Completed response should publish a TaskResult to task.results topic."""
    from nexus.core.kafka.topics import Topics

    raw = _make_response_raw(status="success")
    mock_task = MagicMock()
    mock_task.parent_task_id = str(uuid4())
    mock_task.assigned_agent_id = "test-engineer"
    mock_session_factory = _make_session_factory(mock_task)
    published: list[tuple[str, object]] = []

    async def capture(topic: str, msg: object, *, key: str | None = None) -> None:
        published.append((topic, msg))

    with (
        patch(
            "nexus.kafka.result_consumer.check_idempotency",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("nexus.kafka.result_consumer.publish", side_effect=capture),
        patch("nexus.kafka.result_consumer.redis_pubsub", new_callable=AsyncMock),
    ):
        await _handle_response(raw, mock_session_factory)

    assert len(published) == 1
    topic, _ = published[0]
    # Subtask responses are forwarded to CEO via task.queue (ADR-021)
    assert topic == Topics.TASK_QUEUE


@pytest.mark.asyncio
async def test_handle_response_gracefully_handles_invalid_message() -> None:
    """Malformed raw message should be skipped without raising."""
    raw = {"garbage": "data", "no_required_fields": True}
    mock_session_factory = MagicMock()

    # Should not raise
    await _handle_response(raw, mock_session_factory)
    mock_session_factory.assert_not_called()
