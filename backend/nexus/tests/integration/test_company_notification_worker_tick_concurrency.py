"""Concurrent actual staging creates one wake/draft/action across separate operation instances."""

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.tests.integration.test_company_notification_worker_tick import (
    require_pending_conservation,
)
from nexus.tests.notification_worker_tick_fixture import (
    worker_tick_factory,
    worker_tick_native_case,
)
from nexus.tests.notification_worker_tick_matrix_support import tick_ledger
from nexus.tests.notification_worker_tick_services_fixture import configured_tick_services

__all__ = ["worker_tick_factory"]


async def test_concurrent_ticks_aggregate_one_native_publication_and_pending_action(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await worker_tick_native_case(worker_tick_factory, tmp_path / "blobs")
    services = await configured_tick_services(worker_tick_factory, tmp_path, case)
    before = await tick_ledger(worker_tick_factory)
    workers = tuple(NotificationReadPreparationWorker(services, enabled=True) for _ in range(2))
    results = await asyncio.gather(*(worker.tick() for worker in workers))
    assert sum(result.new_wakes for result in results) == 1
    drafts = tuple(value for result in results for value in result.draft_ids)
    actions = tuple(value for result in results for value in result.action_ids)
    assert len(drafts) == len(actions) == 1
    after = await tick_ledger(worker_tick_factory)
    assert after.publication[:4] == tuple(value + 1 for value in before.publication[:4])
    assert after.publication[4] == after.publication[5]
    assert len(after.journal_ids) == len(before.journal_ids) + 1
    after.require_no_effects()
    await require_pending_conservation(worker_tick_factory, case, drafts[0], actions[0])
