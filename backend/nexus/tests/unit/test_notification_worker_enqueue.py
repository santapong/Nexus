"""Targeted enqueue denies disabled or ambiguous native action state before queue work."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.worker_enqueue import (
    authorize_and_enqueue_prepared_notification,
    require_only_authorized_unissued_action,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.tests.notification_worker_phase3_unit_fixture import dispatch_services
from nexus.tests.unit.test_company_notification_worker_services import guarded_services


async def test_disabled_targeted_enqueue_does_not_read_the_database(tmp_path: Path) -> None:
    value = dispatch_services(tmp_path)
    _, guard = await guarded_services(tmp_path)
    bound = guard.registration.sender
    selection = NativeNotificationSelection(
        company_id=bound.company_id,
        draft_id=UUID(int=830),
        sender_task_id=bound.task_id,
        plan=guard.registration.plan,
    )
    with pytest.raises(NotificationUnavailableError):
        await authorize_and_enqueue_prepared_notification(
            value,
            selection,
            guard.witness,
            guard.snapshot,
        )
    cast(MagicMock, value.reads.factory).assert_not_called()


@pytest.mark.parametrize("actual", [(), (UUID(int=831),), (UUID(int=830), UUID(int=831))])
async def test_other_or_missing_authorized_action_cannot_be_hidden_by_existing_dispatch(
    actual: tuple[UUID, ...],
) -> None:
    session = MagicMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = actual
    session.scalars = AsyncMock(return_value=result)
    work = ExecutionWork(company_id=UUID(int=1), task_id=UUID(int=2), trace_id=UUID(int=3))
    with pytest.raises(NotificationUnavailableError):
        await require_only_authorized_unissued_action(session, work, UUID(int=830))
    session.scalars.assert_awaited_once()


async def test_single_exact_authorized_unissued_action_is_only_a_selection_check() -> None:
    session = MagicMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = (UUID(int=830),)
    session.scalars = AsyncMock(return_value=result)
    work = ExecutionWork(company_id=UUID(int=1), task_id=UUID(int=2), trace_id=UUID(int=3))
    await require_only_authorized_unissued_action(session, work, UUID(int=830))
    session.commit.assert_not_called()
