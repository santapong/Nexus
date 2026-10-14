"""An actual M1 approval under a historical-plan action ID cannot replace current admission."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.actions import ActionProposal
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.managed_admission import notification_action_id
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_managed_execution import mock_dispatch
from nexus.tests.notification_managed_fixture import configured_sender
from nexus.tests.notification_native_support import notifications_factory

__all__ = ["notifications_factory"]


async def test_historical_plan_action_with_real_owner_approval_cannot_issue_current_sender(
    notifications_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_sender(notifications_factory, tmp_path)
    prepared = await case.preparation.prepare(control(), identity(OWNER), case.selection)
    sender = prepared.sender
    older = ActionProposal.model_validate_json(
        prepared.action.proposal.model_copy(
            update={
                "action_id": notification_action_id(
                    case.previous_plan, sender.task_id, case.selection.draft_id
                )
            }
        ).model_dump_json()
    )
    scope = LedgerScope(
        company_id=sender.company_id,
        principal_id=OWNER,
        task_id=sender.task_id,
        trace_id=sender.trace_id,
    )
    journal = CompanyJournal(notifications_factory)
    await journal.submit(older, scope)
    await journal.approve_registered(
        scope, older.action_id, action_hash(older), datetime.now(UTC), identity=identity(OWNER)
    )
    await journal.authorize_registered(
        scope, older.action_id, datetime.now(UTC), (), identity=identity(OWNER)
    )
    lease = await case.execution.claim(scope, identity(OWNER), uuid4())
    before = await case.execution.get(scope, identity(OWNER))
    calls: list[str] = []
    dispatch = mock_dispatch(notifications_factory, case, calls)
    with pytest.raises(ValueError):
        await dispatch.dispatch(lease, identity(OWNER), case.selection.draft_id, older.action_id)
    assert calls == []
    assert (await case.execution.get(scope, identity(OWNER))).counters == before.counters
    async with runtime_transaction(notifications_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.get(EffectIntent, (lease.company_id, older.action_id)) is None
        assert (
            await session.get(NotificationDispatchRow, (lease.company_id, case.selection.draft_id))
            is None
        )
