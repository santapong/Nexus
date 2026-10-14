"""Retained independent target revoke probe; committed intent never supplies stale READ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange
from nexus.company.brain.access_models import BrainResource
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import AttemptKind, EffectStart, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.journal_models import CompanyControl, CostHold
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_dispatch_support import actual_sender, dispatch_factory
from nexus.tests.notification_native_support import configured_notifications

__all__ = ["dispatch_factory"]


@pytest.mark.parametrize("condition", ["revoked", "expires_after_lookup"])
async def test_current_target_read_revoked_after_real_intent_denies_before_post(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    condition: str,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(dispatch_factory, draft)
    original = effects.begin
    calls: list[str] = []

    async def begin(
        current: ExecutionLease,
        actor: VerifiedIdentity,
        action_id: UUID,
        *,
        resources: tuple[ResourceRevision, ...] = (),
        kind: AttemptKind = "tool_attempts",
        before_intent: BeforeIntentCheck | None = None,
    ) -> EffectStart:
        started = await original(
            current, actor, action_id, resources=resources, kind=kind, before_intent=before_intent
        )
        assert started.permit_external_call
        async with management_owner_transaction(dispatch_factory, control(), identity(OWNER)) as (
            session,
            _,
            _,
        ):
            resource = await session.get(BrainResource, (COMPANY, target.resource_id))
            assert resource is not None
            generation = resource.acl_generation
        await ResourceAccessStore(dispatch_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=target,
                principal_id=OWNER,
                active=condition != "revoked",
                expected_generation=generation,
                expires_at=datetime.now(UTC) + timedelta(seconds=3)
                if condition != "revoked"
                else None,
            ),
        )
        return started

    monkeypatch.setattr(effects, "begin", begin)
    revalidate = effects.revalidate_execution_locked

    async def delayed(
        session: AsyncSession,
        current_control: CompanyControl,
        work: ExecutionWork,
        actor: VerifiedIdentity,
        proposal: ActionProposal,
        kind: AttemptKind,
    ) -> None:
        await revalidate(session, current_control, work, actor, proposal, kind)
        if condition == "expires_after_lookup":
            for _ in range(3):
                await session.execute(select(func.pg_sleep(1.1)))

    monkeypatch.setattr(effects, "revalidate_execution_locked", delayed)

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"id": str(UUID(int=8300))})

    service = NotificationDispatchStore(
        dispatch_factory,
        drafts,
        effects,
        target,
        "owner.notifications",
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("fixture-only"),
            http_transport=httpx.MockTransport(response),
        ),
    )
    with pytest.raises(ValueError):
        await service.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id)
    assert calls == []
    saved = await effects.get(lease, identity(OWNER), action.action_id)
    assert saved.state == "intent" and saved.receipt is None
    assert await service.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id) is None
    assert calls == []
    async with runtime_transaction(dispatch_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        hold = await session.get(CostHold, action.action_id)
        assert hold is not None and hold.state == "held" and hold.actual_usd is None
