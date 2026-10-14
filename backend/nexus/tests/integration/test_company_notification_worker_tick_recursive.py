"""A fully qualified existing sender decision wake must not recursively create review work."""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_fact_contracts import DecisionState
from nexus.company.notifications.native_facts import NativeNotificationFact
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_facts import QualifiedNotificationFact
from nexus.company.notifications.worker_config import WorkerConfigurationError
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.harness.journal_models import CompanyControl
from nexus.tests.notification_worker_tick_fixture import (
    worker_tick_factory,
    worker_tick_native_case,
)
from nexus.tests.notification_worker_tick_matrix_support import (
    configure_worker,
    emit_decision,
    tick_ledger,
)
from nexus.tests.notification_worker_tick_services_fixture import configured_tick_services

__all__ = ["worker_tick_factory"]


def record_qualified_self_decision(
    monkeypatch: pytest.MonkeyPatch,
    event_id: UUID,
    sender_id: UUID,
    seen: list[UUID],
) -> None:
    original = QualifiedNotificationFactAdapter.load

    async def delegated(
        self: QualifiedNotificationFactAdapter,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        event: OutboxEvent,
    ) -> NativeNotificationFact:
        fact = await original(self, session, control, scope, identity, event)
        if event.event_id == event_id:
            assert isinstance(fact, QualifiedNotificationFact)
            assert isinstance(fact.native_state, DecisionState)
            assert fact.native_state.work.task_id == sender_id
            assert fact.native_state.action.proposal.tool == "company.owner-notification.send.v1"
            seen.append(event_id)
        return fact

    monkeypatch.setattr(QualifiedNotificationFactAdapter, "load", delegated)


async def test_existing_licensed_sender_wake_denies_after_full_qualification_without_ack(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await worker_tick_native_case(worker_tick_factory, tmp_path / "blobs")
    services = await configured_tick_services(worker_tick_factory, tmp_path, case)
    first = await NotificationReadPreparationWorker(services, enabled=True).tick()
    assert len(first.action_ids) == 1
    self_event = await emit_decision(services, first.action_ids[0])
    configure_worker(tmp_path, emit=False, consume=True, prepare=False)
    before = await tick_ledger(worker_tick_factory)
    seen: list[UUID] = []
    record_qualified_self_decision(
        monkeypatch,
        self_event,
        case.notification.children[0].binding.task_id,
        seen,
    )
    with pytest.raises(WorkerConfigurationError):
        await NotificationReadPreparationWorker(services, enabled=True).tick()
    assert seen == [self_event]
    after = await tick_ledger(worker_tick_factory)
    assert after == before
    after.require_no_effects()
