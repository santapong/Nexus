"""Deferred native M1 tuple resolves only when the actual intent commits in the same transaction."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.notification_models import NotificationDispatchRow
from nexus.execution.runtime_models import EffectIntent
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.notification_intent_schema_support import SchemaBinding, authorized_schema_work
from nexus.tests.notification_schema_support import (
    notification_schema_factory as notification_schema_factory,
)
from nexus.tests.notification_schema_support import persist_schema_draft


async def test_actual_before_intent_deferred_binding_and_intent_commit_once(
    notification_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case, lease, action = await authorized_schema_work(notification_schema_factory, tmp_path)
    draft = await persist_schema_draft(notification_schema_factory, lease.task_id)
    first = await case.native.effects.begin(
        lease, identity(lease.actor_id), action, before_intent=SchemaBinding(draft)
    )
    assert first.permit_external_call is True
    second = await case.native.effects.begin(
        lease,
        identity(lease.actor_id),
        action,
        before_intent=SchemaBinding(draft, mismatch="trace"),
    )
    assert second.permit_external_call is False and second.record == first.record
    async with notification_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        row = await session.get(NotificationDispatchRow, (COMPANY, draft.draft_id))
        intent = await session.get(EffectIntent, (COMPANY, action))
        assert row is not None and intent is not None
        assert (row.trace_id, row.intent_fence, row.proposal_sha256, row.attempt_kind) == (
            intent.trace_id,
            intent.intent_fence,
            intent.proposal_hash,
            intent.attempt_kind,
        )
        assert await session.scalar(select(func.count()).select_from(NotificationDispatchRow)) == 1


@pytest.mark.parametrize("mismatch", ["trace", "fence", "proposal", "kind"])
async def test_wrong_exact_native_intent_tuple_rolls_back_binding_intent_and_counters(
    notification_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path, mismatch: str
) -> None:
    case, lease, action = await authorized_schema_work(notification_schema_factory, tmp_path)
    draft = await persist_schema_draft(notification_schema_factory, lease.task_id)
    before = await saved_m1(notification_schema_factory)
    with pytest.raises(DBAPIError):
        await case.native.effects.begin(
            lease,
            identity(lease.actor_id),
            action,
            before_intent=SchemaBinding(draft, mismatch=mismatch),
        )
    assert await saved_m1(notification_schema_factory) == before
    async with notification_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(NotificationDispatchRow)) == 0
        assert await session.get(EffectIntent, (COMPANY, action)) is None
