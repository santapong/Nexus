"""Real final M1 flush crosses registered digest expiry; no fake DB clock or provider call."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import db_now, lease_scope, runtime_transaction
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_digest_fixture import configured_digest
from nexus.tests.notification_inbox_api_support import inbox_factory
from nexus.tests.notification_managed_execution import approved_sender, mock_dispatch

__all__ = ["inbox_factory"]


async def test_actual_digest_registration_expiry_after_intent_flush_rolls_back_slot_and_intent(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, cases = await configured_digest(inbox_factory, tmp_path, "daily", expires_after=30)
    case = cases[0]
    prepared, lease = await approved_sender(inbox_factory, case)
    action_id = prepared.action.proposal.action_id
    assert isinstance(case.drafts.loader, QualifiedNotificationFactAdapter)
    registration = case.drafts.loader.reader.services.digests[0]
    original = AsyncSession.flush
    reached = False

    async def delayed(self: AsyncSession, objects: Sequence[object] | None = None) -> None:
        nonlocal reached
        relevant = any(
            isinstance(row, EffectIntent) and row.action_id == action_id for row in self.new
        )
        await original(self, objects)
        if relevant:
            reached = True
            for _ in range(62):
                if await db_now(self) >= registration.expires_at:
                    break
                await self.execute(select(func.pg_sleep(0.5)))
            assert await db_now(self) >= registration.expires_at

    monkeypatch.setattr(AsyncSession, "flush", delayed)
    calls: list[str] = []
    with pytest.raises(ValueError):
        await mock_dispatch(inbox_factory, case, calls).dispatch(
            lease, identity(OWNER), case.selection.draft_id, action_id
        )
    assert reached and calls == []
    async with runtime_transaction(inbox_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.get(EffectIntent, (lease.company_id, action_id)) is None
        assert (
            await session.get(NotificationDispatchRow, (lease.company_id, case.selection.draft_id))
            is None
        )
