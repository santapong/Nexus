"""Native owner-approved sender partition and pending approval feed one actual managed permit."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.managed_dispatch import ManagedNotificationDispatchStore
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.harness.lifecycle import ActionState
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_managed_fixture import configured_sender
from nexus.tests.notification_native_support import notifications_factory

__all__ = ["notifications_factory"]


async def test_pending_only_then_exact_owner_approval_managed_claim_and_one_post(
    notifications_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_sender(notifications_factory, tmp_path)
    sender = case.metric.payload.children[-1].binding
    scope = LedgerScope(
        company_id=sender.company_id,
        principal_id=OWNER,
        task_id=sender.task_id,
        trace_id=sender.trace_id,
    )
    before = await case.execution.get(scope, identity(OWNER))
    prepared = await case.preparation.prepare(control(), identity(OWNER), case.selection)
    assert prepared.action.state == ActionState.AWAITING_APPROVAL and prepared.call_permit is False
    assert await case.preparation.prepare(control(), identity(OWNER), case.selection) == prepared
    assert (await case.execution.get(scope, identity(OWNER))).counters == before.counters
    async with runtime_transaction(notifications_factory, scope, identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.get(CostHold, prepared.action.proposal.action_id) is None
    journal, action = CompanyJournal(notifications_factory), prepared.action.proposal
    await journal.approve_registered(
        scope, action.action_id, action_hash(action), datetime.now(UTC), identity=identity(OWNER)
    )
    await journal.authorize_registered(
        scope, action.action_id, datetime.now(UTC), (), identity=identity(OWNER)
    )
    lease = await case.execution.claim(scope, identity(OWNER), uuid4())
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"id": str(UUID(int=8410))})

    service = ManagedNotificationDispatchStore(
        notifications_factory,
        case.drafts,
        case.effects,
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("fixture-only"),
            http_transport=httpx.MockTransport(response),
        ),
    )
    result = await service.dispatch(
        lease, identity(OWNER), case.selection.draft_id, action.action_id
    )
    assert result is not None and result.outcome == "accepted" and calls == ["POST"]
    first = await case.effects.get(lease, identity(OWNER), action.action_id)
    assert first.receipt is not None and first.receipt.outcome == "succeeded"
    assert (
        await service.dispatch(lease, identity(OWNER), case.selection.draft_id, action.action_id)
        is None
    )
    after = await case.execution.get(scope, identity(OWNER))
    assert after.counters.tool_attempts == before.counters.tool_attempts + 1
    assert after.counters.model_requests == before.counters.model_requests
    assert after.state == "verifying"
    async with runtime_transaction(notifications_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        hold = await session.get(CostHold, action.action_id)
        assert hold is not None and hold.actual_usd is None and hold.state == "unknown"
        assert hold.amount_usd == case.policy.estimated_cost_usd
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ManagementWorkAcceptance)
                .where(ManagementWorkAcceptance.author_task_id == sender.task_id)
            )
            == 0
        )


@pytest.mark.parametrize("failure", ["wrong_owner", "old_plan"])
async def test_managed_prepare_rejects_wrong_owner_or_plan_selector(
    notifications_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    case = await configured_sender(notifications_factory, tmp_path)
    if failure == "wrong_owner":
        actor, selected = identity(UUID(int=4)), case.selection
    else:
        actor = identity(OWNER)
        selected = case.selection.model_copy(update={"plan": case.previous_plan})
    with pytest.raises(ValueError):
        await case.preparation.prepare(control(), actor, selected)
    async with management_owner_transaction(notifications_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JournalAction)
                .where(JournalAction.task_id == case.selection.sender_task_id)
            )
            == 0
        )
