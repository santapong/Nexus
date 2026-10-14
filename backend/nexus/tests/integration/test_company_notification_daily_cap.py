"""Unknown sends consume Bangkok slots across distinct native accepted work."""

from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationPolicy
from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.runtime_models import EffectIntent
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_cap_fixture import distinct_report_case
from nexus.tests.notification_dispatch_support import actual_sender, dispatch_factory
from nexus.tests.notification_native_support import configured_notifications

__all__ = ["dispatch_factory"]


async def test_unknown_first_actual_intent_exhausts_slot_for_new_native_work_state(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    drafts.policy = NotificationPolicy(
        enabled=True, routine_per_day=1, major_completion_task_ids=case.request.task_ids
    )
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    first = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(dispatch_factory, first)
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise httpx.ReadTimeout("offline-unknown", request=request)

    config = NotificationTransportConfiguration(
        enabled=True,
        api_key=SecretStr("fixture-only"),
        http_transport=httpx.MockTransport(response),
    )
    service = NotificationDispatchStore(
        dispatch_factory, drafts, effects, target, "owner.notifications", configuration=config
    )
    first_result = await service.dispatch(lease, identity(OWNER), first.draft_id, action.action_id)
    assert first_result is not None and first_result.outcome == "unknown"
    second_case = await distinct_report_case(dispatch_factory, case)
    drafts.policy = NotificationPolicy(
        enabled=True,
        routine_per_day=1,
        major_completion_task_ids=(*case.request.task_ids, *second_case.request.task_ids),
    )
    await accept_report(dispatch_factory, second_case)
    async with management_owner_transaction(dispatch_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        event_id = await session.scalar(
            select(BrainEvent.event_id)
            .where(BrainEvent.company_id == COMPANY, BrainEvent.kind == "verification_recorded")
            .order_by(BrainEvent.sequence.desc())
            .limit(1)
        )
        assert event_id is not None
    second = await drafts.publish_event(control(), identity(OWNER), event_id)
    assert second.draft_id != first.draft_id
    other, proposal, other_effects, other_target = await actual_sender(dispatch_factory, second)
    next_service = NotificationDispatchStore(
        dispatch_factory,
        drafts,
        other_effects,
        other_target,
        "owner.notifications",
        configuration=config,
    )
    with pytest.raises(NotificationUnavailableError, match="daily cap"):
        await next_service.dispatch(other, identity(OWNER), second.draft_id, proposal.action_id)
    assert calls == ["POST"]
    async with management_owner_transaction(dispatch_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.get(EffectIntent, (COMPANY, proposal.action_id)) is None
