"""Actual registered model qualification expires after native intent flush or committed intent."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import AttemptKind, EffectStart, ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_managed_execution import (
    approved_sender,
    configure_catalog,
    expiring_profile,
    mock_dispatch,
)
from nexus.tests.notification_managed_fixture import configured_sender
from nexus.tests.notification_native_support import notifications_factory

__all__ = ["notifications_factory"]


@pytest.mark.parametrize("phase", ["after_flush", "after_commit"])
async def test_model_expiry_after_actual_boundary_never_reaches_mock_post(
    notifications_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    case = await configured_sender(notifications_factory, tmp_path)
    case = configure_catalog(notifications_factory, case, expiring_profile(case, 8))
    prepared, lease = await approved_sender(notifications_factory, case)
    action_id = prepared.action.proposal.action_id
    seen = False
    original_flush = AsyncSession.flush

    async def flush(self: AsyncSession, objects: Sequence[object] | None = None) -> None:
        nonlocal seen
        relevant = any(
            isinstance(row, EffectIntent) and row.action_id == action_id for row in self.new
        )
        await original_flush(self, objects)
        if relevant and phase == "after_flush":
            seen = True
            for _ in range(8):
                await self.execute(select(func.pg_sleep(1.1)))

    original_begin = case.effects.begin

    async def begin(
        current: ExecutionLease,
        actor: VerifiedIdentity,
        current_action_id: UUID,
        *,
        resources: tuple[ResourceRevision, ...] = (),
        kind: AttemptKind = "tool_attempts",
        before_intent: BeforeIntentCheck | None = None,
    ) -> EffectStart:
        nonlocal seen
        started = await original_begin(
            current,
            actor,
            current_action_id,
            resources=resources,
            kind=kind,
            before_intent=before_intent,
        )
        if phase == "after_commit":
            assert started.permit_external_call
            seen = True
            async with notifications_factory() as session:
                for _ in range(8):
                    await session.execute(select(func.pg_sleep(1.1)))
        return started

    monkeypatch.setattr(AsyncSession, "flush", flush)
    monkeypatch.setattr(case.effects, "begin", begin)
    calls: list[str] = []
    dispatch = mock_dispatch(notifications_factory, case, calls)
    with pytest.raises(ValueError):
        await dispatch.dispatch(lease, identity(OWNER), case.selection.draft_id, action_id)
    assert seen and calls == []
    async with runtime_transaction(notifications_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        intent = await session.get(EffectIntent, (lease.company_id, action_id))
        slot = await session.get(
            NotificationDispatchRow, (lease.company_id, case.selection.draft_id)
        )
        if phase == "after_flush":
            assert intent is None and slot is None
        else:
            assert intent is not None and intent.state == "intent" and slot is not None
    if phase == "after_commit":
        assert (
            await dispatch.dispatch(lease, identity(OWNER), case.selection.draft_id, action_id)
            is None
        )
        assert calls == []
