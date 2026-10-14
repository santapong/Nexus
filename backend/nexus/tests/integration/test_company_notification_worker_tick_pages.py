"""Actual public drafts recover through bounded licensed pages and one worker restart."""

from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.managed_admission import notification_action_id
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_worker_tick import (
    require_pending_conservation,
)
from nexus.tests.notification_worker_tick_fixture import (
    WorkerTickNativeCase,
    worker_tick_factory,
    worker_tick_native_case,
)
from nexus.tests.notification_worker_tick_matrix_support import (
    configure_worker,
    three_pending_sources,
    tick_ledger,
)
from nexus.tests.notification_worker_tick_services_fixture import configured_tick_services

__all__ = ["worker_tick_factory"]


def record_real_visited_pages(
    monkeypatch: pytest.MonkeyPatch,
    seen: list[tuple[UUID, ...]],
) -> None:
    original = QualifiedNotificationDraftStore.qualify_visited_batch_locked

    async def visited(
        self: QualifiedNotificationDraftStore,
        session: AsyncSession,
        actual: CompanyControl,
        scope: CompanyControlScope,
        actor: VerifiedIdentity,
        draft_ids: tuple[UUID, ...],
    ) -> tuple[datetime, ...]:
        result = await original(self, session, actual, scope, actor, draft_ids)
        seen.append(draft_ids)
        return result

    monkeypatch.setattr(QualifiedNotificationDraftStore, "qualify_visited_batch_locked", visited)


async def require_all_exact_pending(
    factory: async_sessionmaker[AsyncSession],
    case: WorkerTickNativeCase,
    draft_ids: tuple[UUID, ...],
    action_ids: tuple[UUID, ...],
) -> None:
    for draft_id, action_id in zip(draft_ids, action_ids, strict=True):
        await require_pending_conservation(factory, case, draft_id, action_id)
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        sender = case.notification.children[0].binding
        rows = tuple(
            (
                await session.scalars(
                    select(JournalAction).where(JournalAction.task_id == sender.task_id)
                )
            ).all()
        )
        assert {row.id for row in rows} == set(action_ids)
        assert all(pending_action_record(row).approval is None for row in rows)


async def test_three_real_drafts_prepare_without_skipping_after_restart_and_page_cycle(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await worker_tick_native_case(worker_tick_factory, tmp_path / "blobs")
    services = await configured_tick_services(worker_tick_factory, tmp_path, case)
    source_actions = await three_pending_sources(worker_tick_factory, case, services)
    configure_worker(tmp_path, emit=False, consume=True, prepare=False, max_candidates=1)
    published = await NotificationReadPreparationWorker(services, enabled=True).tick()
    assert len(published.draft_ids) == 3 and not published.action_ids
    assert len(source_actions) == 3
    configure_worker(tmp_path, emit=False, consume=False, prepare=True, max_candidates=1)
    seen: list[tuple[UUID, ...]] = []
    record_real_visited_pages(monkeypatch, seen)
    first = await NotificationReadPreparationWorker(services, enabled=True).tick()
    assert len(first.action_ids) == 1
    restarted = NotificationReadPreparationWorker(services, enabled=True)
    later = [await restarted.tick() for _ in range(8)]
    actual = (
        *first.action_ids,
        *(action_id for result in later for action_id in result.action_ids),
    )
    assert len(set(actual)) == len(actual) == 3
    registration = services.registrations.snapshot().value.registration
    expected = tuple(
        notification_action_id(registration.plan, registration.sender.task_id, draft_id)
        for draft_id in published.draft_ids
    )
    assert set(actual) == set(expected)
    assert all(result.disposition == "quiet" for result in later[3:])
    before_quiet = await tick_ledger(worker_tick_factory)
    assert (await restarted.tick()).disposition == "quiet"
    after_quiet = await tick_ledger(worker_tick_factory)
    assert after_quiet == before_quiet
    after_quiet.require_no_effects()
    assert any(len(ids) >= 3 for ids in seen) and all(len(ids) <= 3 for ids in seen)
    assert all(set(ids) <= set(published.draft_ids) for ids in seen)
    await require_all_exact_pending(worker_tick_factory, case, published.draft_ids, expected)
