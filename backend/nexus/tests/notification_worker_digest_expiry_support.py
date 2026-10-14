"""TEST-only real finite registration and read-only nomination of actual staging final clocks."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain import native_fact_emitter
from nexus.company.brain.event_models import BrainEvent, BrainEventCursor
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications import managed_preparation, qualified_consumer
from nexus.company.notifications.draft_models import NotificationDraftRow, NotificationEventLinkRow
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import JournalAction
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_worker_digest_fixture import (
    WorkerDigestCase,
    configure_digest_subject,
    digest_services,
)
from nexus.tests.notification_worker_tick_matrix_support import configure_worker


@dataclass(frozen=True)
class DigestExpiryObservation:
    before: datetime
    after: datetime
    alias_calls: int


async def finite_digest_case(original: WorkerDigestCase, root: Path) -> WorkerDigestCase:
    async with management_owner_transaction(
        original.services.factory, control(), identity(OWNER)
    ) as (session, _, _):
        now = await db_now(session)
    registration = original.registration.model_copy(
        update={
            "registered_at": now - timedelta(minutes=1),
            "expires_at": now + timedelta(seconds=10),
        }
    )
    services = digest_services(original.services, registration)
    configure_digest_subject(root, services, registration)
    return replace(original, services=services, registration=registration)


async def prepare_digest_stage(case: WorkerDigestCase, root: Path, phase: str) -> None:
    if phase == "emitter":
        configure_worker(root, emit=True, consume=False, prepare=False)
        return
    services = case.services
    bound = services.registrations.snapshot().value.registration.sender
    witness = await services.identities.current(expected_binding=bound)
    selector = services.registrations.snapshot().value.registration.subjects[0].selector
    event = await NativeFactEmitter(services.factory, NativeFactReader(services.facts)).emit(
        owner_scope(control(), witness.identity),
        witness.identity,
        selector,
    )
    assert event is not None and event.kind == "digest_due"
    configure_worker(root, emit=False, consume=True, prepare=False)
    if phase == "preparation":
        consumed = await NotificationReadPreparationWorker(services, enabled=True).tick()
        assert len(consumed.draft_ids) == 1 and consumed.action_ids == ()
        configure_worker(root, emit=False, consume=False, prepare=True)
    else:
        assert phase == "consumer"


async def require_flushed_phase(session: AsyncSession, case: WorkerDigestCase, phase: str) -> None:
    if phase == "emitter":
        count = await session.scalar(
            select(func.count()).select_from(BrainEvent).where(BrainEvent.kind == "digest_due")
        )
        assert count == 1
    elif phase == "consumer":
        cursor = await session.get(
            BrainEventCursor, (COMPANY, "nexus.notifications.worker", "native-notification-read-v1")
        )
        sequence = await session.scalar(select(func.max(BrainEvent.sequence)))
        assert cursor is not None and cursor.last_sequence == sequence
        assert await session.scalar(select(func.count()).select_from(NotificationDraftRow)) == 1
        assert await session.scalar(select(func.count()).select_from(NotificationEventLinkRow)) == 1
    else:
        assert phase == "preparation"
        sender = case.native.notification.children[0].binding
        rows = tuple(
            (
                await session.scalars(
                    select(JournalAction).where(JournalAction.task_id == sender.task_id)
                )
            ).all()
        )
        assert len(rows) == 1 and rows[0].state == "awaiting_approval"
        assert rows[0].approval_json is None and rows[0].consumed_at is None


def nominate_digest_final_clock(
    monkeypatch: pytest.MonkeyPatch,
    case: WorkerDigestCase,
    phase: str,
    seen: list[DigestExpiryObservation],
) -> None:
    modules: dict[str, ModuleType] = {
        "emitter": native_fact_emitter,
        "consumer": qualified_consumer,
        "preparation": managed_preparation,
    }
    module = modules[phase]
    assert vars(module)["db_now"] is db_now
    original: Callable[[AsyncSession], Awaitable[datetime]] = db_now
    expected_calls = 2 if phase == "emitter" else 1
    calls = 0

    async def crossing(session: AsyncSession) -> datetime:
        nonlocal calls
        calls += 1
        assert calls <= expected_calls
        before = await original(session)
        if calls != expected_calls:
            assert before < case.registration.expires_at
            return before
        await require_flushed_phase(session, case, phase)
        before = await original(session)
        assert before < case.registration.expires_at
        remaining = (case.registration.expires_at - datetime.now(UTC)).total_seconds()
        assert 0 < remaining < 15
        await asyncio.sleep(remaining + 0.03)
        after = await original(session)
        assert after >= case.registration.expires_at
        seen.append(DigestExpiryObservation(before, after, calls))
        return after

    monkeypatch.setattr(module, "db_now", crossing)
