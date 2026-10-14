"""Unknown submission keeps the weekly native slot and bill unknown; never resend."""

from pathlib import Path

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.managed_dispatch import ManagedNotificationDispatchStore
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.journal_models import CostHold
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_digest_fixture import configured_digest
from nexus.tests.notification_inbox_api_support import inbox_factory
from nexus.tests.notification_managed_execution import approved_sender

__all__ = ["inbox_factory"]


async def test_unknown_weekly_submission_permanently_consumes_slot_without_resend_or_zero_bill(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    _, cases = await configured_digest(inbox_factory, tmp_path, "weekly")
    case = cases[0]
    prepared, lease = await approved_sender(inbox_factory, case)
    action_id = prepared.action.proposal.action_id
    calls: list[str] = []

    def unknown(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise httpx.ReadTimeout("Fixture unknown after mock request", request=request)

    service = ManagedNotificationDispatchStore(
        inbox_factory,
        case.drafts,
        case.effects,
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("fixture-only"),
            http_transport=httpx.MockTransport(unknown),
        ),
    )
    result = await service.dispatch(lease, identity(OWNER), case.selection.draft_id, action_id)
    assert result is not None and result.outcome == "unknown" and result.provider_id is None
    assert (
        await service.dispatch(lease, identity(OWNER), case.selection.draft_id, action_id) is None
    )
    assert calls == ["POST"]
    native = await case.effects.get(lease, identity(OWNER), action_id)
    assert native.receipt is not None and native.receipt.outcome == "outcome_unknown"
    async with runtime_transaction(inbox_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        slot = await session.get(
            NotificationDispatchRow, (lease.company_id, case.selection.draft_id)
        )
        hold = await session.get(CostHold, action_id)
        assert slot is not None and slot.kind == "weekly"
        assert hold is not None and hold.actual_usd is None and hold.state == "unknown"
