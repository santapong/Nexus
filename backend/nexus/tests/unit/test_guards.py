"""Unit tests for tools/guards.py — approval workflow."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nexus.db.models import ApprovalStatus
from nexus.tools.guards import (
    ApprovalDeniedError,
    ApprovalTimeoutError,
    IrreversibleAction,
    require_approval,
    resolve_approval,
)


def _make_action() -> IrreversibleAction:
    return IrreversibleAction(
        action="file_write",
        description="Write 100 chars to /tmp/test.txt",
        task_id=str(uuid4()),
    )


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_require_approval_creates_record() -> None:
    """require_approval should create a HumanApproval record in the DB."""
    session = _make_mock_session()
    action = _make_action()

    # Mock the polling to return approved on first poll
    mock_record = MagicMock()
    mock_record.status = ApprovalStatus.APPROVED.value
    mock_record.resolved_by = "human"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_record
    session.execute = AsyncMock(return_value=mock_result)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("nexus.tools.guards._APPROVAL_POLL_SECONDS", 0.01)
        await require_approval(session=session, agent_id="test-agent", action=action)

    # Verify a record was added to the session
    session.add.assert_called_once()
    added_record = session.add.call_args[0][0]
    assert added_record.tool_name == "file_write"
    assert added_record.status == ApprovalStatus.PENDING.value


@pytest.mark.asyncio
async def test_require_approval_raises_on_rejection() -> None:
    """require_approval should raise ApprovalDeniedError when rejected."""
    session = _make_mock_session()
    action = _make_action()

    mock_record = MagicMock()
    mock_record.status = ApprovalStatus.REJECTED.value
    mock_record.resolved_by = "human"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_record
    session.execute = AsyncMock(return_value=mock_result)

    with (
        pytest.MonkeyPatch.context() as mp,
        pytest.raises(ApprovalDeniedError, match="file_write"),
    ):
        mp.setattr("nexus.tools.guards._APPROVAL_POLL_SECONDS", 0.01)
        await require_approval(session=session, agent_id="test-agent", action=action)


@pytest.mark.asyncio
async def test_require_approval_times_out() -> None:
    """require_approval should raise ApprovalTimeoutError after timeout."""
    session = _make_mock_session()
    action = _make_action()

    # Always return pending
    mock_record = MagicMock()
    mock_record.status = ApprovalStatus.PENDING.value

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_record
    session.execute = AsyncMock(return_value=mock_result)

    with (
        pytest.MonkeyPatch.context() as mp,
        pytest.raises(ApprovalTimeoutError),
    ):
        mp.setattr("nexus.tools.guards._APPROVAL_POLL_SECONDS", 0.01)
        mp.setattr("nexus.tools.guards._APPROVAL_TIMEOUT_SECONDS", 0.03)
        await require_approval(session=session, agent_id="test-agent", action=action)


@pytest.mark.asyncio
async def test_resolve_approval_approves() -> None:
    """resolve_approval should update status to approved."""
    session = _make_mock_session()

    mock_record = MagicMock()
    mock_record.id = uuid4()
    mock_record.status = ApprovalStatus.PENDING.value

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_record
    session.execute = AsyncMock(return_value=mock_result)

    result = await resolve_approval(
        session=session,
        approval_id=str(mock_record.id),
        approved=True,
        resolved_by="tester",
    )

    assert result is not None
    assert result.status == ApprovalStatus.APPROVED.value
    assert result.resolved_by == "tester"
    assert result.resolved_at is not None


@pytest.mark.asyncio
async def test_resolve_approval_rejects() -> None:
    """resolve_approval should update status to rejected."""
    session = _make_mock_session()

    mock_record = MagicMock()
    mock_record.id = uuid4()
    mock_record.status = ApprovalStatus.PENDING.value

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_record
    session.execute = AsyncMock(return_value=mock_result)

    result = await resolve_approval(
        session=session,
        approval_id=str(mock_record.id),
        approved=False,
        resolved_by="tester",
    )

    assert result is not None
    assert result.status == ApprovalStatus.REJECTED.value


@pytest.mark.asyncio
async def test_resolve_approval_returns_none_for_unknown() -> None:
    """resolve_approval should return None if record not found."""
    session = _make_mock_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    result = await resolve_approval(
        session=session,
        approval_id=str(uuid4()),
        approved=True,
        resolved_by="tester",
    )

    assert result is None
