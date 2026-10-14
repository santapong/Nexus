"""Distinct genuine report drafts cannot reset digest quota; routine slots stay separate."""

from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_digest_execution import approve_next
from nexus.tests.notification_digest_fixture import configured_digest
from nexus.tests.notification_inbox_api_support import inbox_factory
from nexus.tests.notification_managed_execution import approved_sender, mock_dispatch

__all__ = ["inbox_factory"]


@pytest.mark.parametrize("kind", ["daily", "weekly"])
async def test_distinct_actual_report_drafts_share_one_permanent_company_kind_bucket(
    inbox_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    kind: Literal["daily", "weekly"],
) -> None:
    _, cases = await configured_digest(inbox_factory, tmp_path, kind, report_count=2)
    first, second = cases
    assert first.selection.draft_id != second.selection.draft_id
    initial, lease = await approved_sender(inbox_factory, first)
    next_action = await approve_next(inbox_factory, second)
    calls: list[str] = []
    service = mock_dispatch(inbox_factory, first, calls)
    result = await service.dispatch(
        lease, identity(OWNER), first.selection.draft_id, initial.action.proposal.action_id
    )
    assert result is not None and result.outcome == "accepted"
    with pytest.raises(NotificationUnavailableError, match="digest slot is exhausted"):
        await service.dispatch(
            lease, identity(OWNER), second.selection.draft_id, next_action.action.proposal.action_id
        )
    assert calls == ["POST"]
    async with runtime_transaction(inbox_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.get(
                EffectIntent, (lease.company_id, next_action.action.proposal.action_id)
            )
            is None
        )
        assert (
            await session.get(
                NotificationDispatchRow, (lease.company_id, second.selection.draft_id)
            )
            is None
        )


async def test_exhausted_routine_day_cap_does_not_consume_actual_daily_digest_slot(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    routine, digests = await configured_digest(inbox_factory, tmp_path, "daily")
    initial, lease = await approved_sender(inbox_factory, routine)
    digest = digests[0]
    next_action = await approve_next(inbox_factory, digest)
    calls: list[str] = []
    service = mock_dispatch(inbox_factory, routine, calls)
    assert (
        await service.dispatch(
            lease, identity(OWNER), routine.selection.draft_id, initial.action.proposal.action_id
        )
    ) is not None
    assert (
        await service.dispatch(
            lease, identity(OWNER), digest.selection.draft_id, next_action.action.proposal.action_id
        )
    ) is not None
    assert calls == ["POST", "POST"]
    async with runtime_transaction(inbox_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        kinds = []
        for draft_id in (routine.selection.draft_id, digest.selection.draft_id):
            row = await session.get(NotificationDispatchRow, (lease.company_id, draft_id))
            assert row is not None
            kinds.append(row.kind)
        assert kinds == ["routine", "daily"]
