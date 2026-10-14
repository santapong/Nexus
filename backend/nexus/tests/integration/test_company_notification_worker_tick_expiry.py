"""Actual sender-only public READ expiry rolls back empty and ignored cursor finalization."""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.worker_config import WorkerConfigurationError
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.tests.notification_worker_tick_expiry_support import (
    actual_expired_grant,
    delay_final_consumer_clock,
    finite_sender_grant,
    pending_ignored_kinds,
)
from nexus.tests.notification_worker_tick_fixture import (
    worker_tick_factory,
    worker_tick_native_case,
)
from nexus.tests.notification_worker_tick_matrix_support import configure_worker, tick_ledger
from nexus.tests.notification_worker_tick_services_fixture import configured_tick_services

__all__ = ["worker_tick_factory"]


@pytest.mark.parametrize("shape", ["empty", "ignored"])
async def test_actual_sender_deadline_closes_empty_or_ignored_final_cursor_clock(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
) -> None:
    case = await worker_tick_native_case(worker_tick_factory, tmp_path / "blobs")
    services = await configured_tick_services(worker_tick_factory, tmp_path, case)
    configure_worker(tmp_path, emit=False, consume=True, prepare=False)
    expires = await finite_sender_grant(services)
    worker = NotificationReadPreparationWorker(services, enabled=True)
    if shape == "empty":
        seeded = await worker.tick()
        assert seeded.disposition == "quiet" and seeded.events_acknowledged > 0
    pending = await pending_ignored_kinds(worker_tick_factory)
    assert bool(pending) == (shape == "ignored")
    before = await tick_ledger(worker_tick_factory)
    seen: list[datetime] = []
    delay_final_consumer_clock(monkeypatch, expires, seen)
    with pytest.raises(WorkerConfigurationError):
        await worker.tick()
    assert len(seen) == 1 and seen[0] >= expires
    after = await tick_ledger(worker_tick_factory)
    assert after == before
    after.require_no_effects()
    await actual_expired_grant(services, expires)
