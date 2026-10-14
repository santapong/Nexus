"""Active queue metadata is required in addition to canonical permanent command identity."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.notifications.worker_enqueue import (
    authorize_and_enqueue_prepared_notification,
    require_active_notification_queue,
)
from nexus.tests.notification_worker_enqueue_unit_fixture import enqueue_flow
from nexus.tests.unit.test_notification_worker_contracts import command


async def test_exact_terminal_replay_cannot_be_reported_as_active_stored_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await enqueue_flow(tmp_path, monkeypatch, "terminal")
    with pytest.raises(ValueError):
        await authorize_and_enqueue_prepared_notification(
            case.services,
            case.selection,
            case.credential,
            case.snapshot,
        )
    assert case.events[-1] == "rollback" and "commit" not in case.events
    assert "queued" in case.events and "status_checked" in case.events


@pytest.mark.parametrize("status", ["ENQUEUED", "PENDING"])
async def test_only_literal_active_queue_states_pass_the_locked_observation(status: str) -> None:
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.scalar = AsyncMock(return_value=status)
    await require_active_notification_queue(session, command())
    statement, parameters = session.scalar.await_args.args
    assert "FOR UPDATE" in str(statement)
    assert parameters == {"workflow_id": command().workflow_id}


@pytest.mark.parametrize(
    "status",
    [
        None,
        False,
        "DELAYED",
        "CANCELLED",
        "ERROR",
        "SUCCESS",
        "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
        "ENQUEUED ",
        "unexpected",
    ],
)
async def test_missing_terminal_delayed_or_nonliteral_state_cannot_imply_scheduled_work(
    status: object,
) -> None:
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.scalar = AsyncMock(return_value=status)
    with pytest.raises(ValueError):
        await require_active_notification_queue(session, command())


async def test_queue_observation_requires_the_native_transaction_before_reading() -> None:
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = False
    session.scalar = AsyncMock()
    with pytest.raises(ValueError):
        await require_active_notification_queue(session, command())
    session.scalar.assert_not_awaited()
