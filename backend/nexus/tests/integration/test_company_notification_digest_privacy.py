"""Current source and recipient loss after a real committed digest intent prevents POST."""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import AttemptKind, EffectStart, ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.journal_models import CostHold
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.notification_digest_fixture import configured_digest
from nexus.tests.notification_inbox_api_support import inbox_factory
from nexus.tests.notification_managed_execution import approved_sender, mock_dispatch

__all__ = ["inbox_factory"]


@pytest.mark.parametrize("loss", ["source", "recipient"])
async def test_digest_current_source_or_recipient_loss_after_intent_keeps_slot_without_post(
    inbox_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    loss: str,
) -> None:
    _, cases = await configured_digest(inbox_factory, tmp_path, "daily")
    case = cases[0]
    prepared, lease = await approved_sender(inbox_factory, case)
    action_id = prepared.action.proposal.action_id
    original = case.effects.begin
    reached = False

    async def committed(
        current: ExecutionLease,
        actor: VerifiedIdentity,
        selected: UUID,
        *,
        resources: tuple[ResourceRevision, ...] = (),
        kind: AttemptKind = "tool_attempts",
        before_intent: BeforeIntentCheck | None = None,
    ) -> EffectStart:
        nonlocal reached
        started = await original(
            current, actor, selected, resources=resources, kind=kind, before_intent=before_intent
        )
        assert started.permit_external_call
        reached = True
        if loss == "source":
            await owner_source(inbox_factory, active=False)
        else:
            (tmp_path / "synthetic-managed-recipient.json").unlink()
        return started

    monkeypatch.setattr(case.effects, "begin", committed)
    calls: list[str] = []
    service = mock_dispatch(inbox_factory, case, calls)
    with pytest.raises(ValueError):
        await service.dispatch(lease, identity(OWNER), case.selection.draft_id, action_id)
    assert reached and calls == []
    assert (
        await service.dispatch(lease, identity(OWNER), case.selection.draft_id, action_id) is None
    )
    await require_retained_native_intent(inbox_factory, lease, case.selection.draft_id, action_id)


async def require_retained_native_intent(
    factory: async_sessionmaker[AsyncSession],
    lease: ExecutionLease,
    draft_id: UUID,
    action_id: UUID,
) -> None:
    async with runtime_transaction(factory, lease_scope(lease), identity(OWNER)) as (session, _, _):
        intent = await session.get(EffectIntent, (lease.company_id, action_id))
        slot = await session.get(NotificationDispatchRow, (lease.company_id, draft_id))
        hold = await session.get(CostHold, action_id)
        assert intent is not None and intent.state == "intent" and intent.receipt_json is None
        assert slot is not None and slot.kind == "daily"
        assert hold is not None and hold.actual_usd is None and hold.state == "held"
        assert hold.amount_usd > 0
