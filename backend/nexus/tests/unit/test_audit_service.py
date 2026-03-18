"""Unit tests for audit/service.py — log_event creates correct records."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nexus.audit.service import AuditEventType, log_event


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_log_event_creates_audit_record() -> None:
    """log_event should add an AuditLog record to the session."""
    session = _make_mock_session()
    task_id = str(uuid4())
    trace_id = str(uuid4())

    await log_event(
        session=session,
        task_id=task_id,
        trace_id=trace_id,
        agent_id="test-agent",
        event_type=AuditEventType.TASK_RECEIVED,
        event_data={"role": "engineer", "instruction": "test"},
    )

    session.add.assert_called_once()
    record = session.add.call_args[0][0]
    assert record.task_id == task_id
    assert record.trace_id == trace_id
    assert record.agent_id == "test-agent"
    assert record.event_type == "task_received"
    assert record.event_data == {"role": "engineer", "instruction": "test"}


@pytest.mark.asyncio
async def test_log_event_accepts_string_event_type() -> None:
    """log_event should accept a plain string event_type."""
    session = _make_mock_session()

    await log_event(
        session=session,
        task_id=str(uuid4()),
        trace_id=str(uuid4()),
        agent_id="test-agent",
        event_type="custom_event",
        event_data={"key": "value"},
    )

    record = session.add.call_args[0][0]
    assert record.event_type == "custom_event"


@pytest.mark.asyncio
async def test_log_event_all_event_types() -> None:
    """All AuditEventType values should be usable."""
    session = _make_mock_session()

    for event_type in AuditEventType:
        session.add.reset_mock()
        await log_event(
            session=session,
            task_id=str(uuid4()),
            trace_id=str(uuid4()),
            agent_id="test-agent",
            event_type=event_type,
            event_data={},
        )
        record = session.add.call_args[0][0]
        assert record.event_type == event_type.value


@pytest.mark.asyncio
async def test_log_event_preserves_event_data() -> None:
    """Complex event_data dicts should be stored as-is."""
    session = _make_mock_session()
    complex_data = {
        "model_name": "claude-sonnet-4-20250514",
        "input_tokens": 1500,
        "output_tokens": 300,
        "cost_usd": 0.009,
        "nested": {"key": [1, 2, 3]},
    }

    await log_event(
        session=session,
        task_id=str(uuid4()),
        trace_id=str(uuid4()),
        agent_id="test-agent",
        event_type=AuditEventType.LLM_CALL,
        event_data=complex_data,
    )

    record = session.add.call_args[0][0]
    assert record.event_data == complex_data
