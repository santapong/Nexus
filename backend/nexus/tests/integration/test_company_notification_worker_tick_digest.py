"""Actual protected owner snapshot and Bangkok bucket staging; no acceptance or send claim."""

from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.tests.notification_worker_digest_fixture import (
    digest_native_counts,
    require_digest_pins,
    worker_digest_case,
)
from nexus.tests.notification_worker_tick_fixture import worker_tick_factory
from nexus.tests.notification_worker_tick_matrix_support import tick_ledger

__all__ = ["worker_tick_factory"]


@pytest.mark.parametrize("kind", ["weekly", "daily"])
async def test_actual_saved_report_digest_respects_current_bucket_and_worker_restart(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    kind: Literal["daily", "weekly"],
    record_property: Callable[[str, object], None],
) -> None:
    case = await worker_digest_case(worker_tick_factory, tmp_path, kind)
    record_property("actual_clock_utc", case.clock_observed.isoformat())
    record_property("actual_digest_disposition", "eligible" if case.window else "not_due")
    record_property("actual_due_bucket", case.window[0] if case.window else None)
    before = await digest_native_counts(worker_tick_factory)
    worker = NotificationReadPreparationWorker(case.services, enabled=True)
    first = await worker.tick()
    if case.window is None:
        assert first.disposition == "quiet" and first.new_wakes == 0
        assert first.draft_ids == first.action_ids == ()
        assert await digest_native_counts(worker_tick_factory) == before
        assert (
            await NotificationReadPreparationWorker(case.services, enabled=True).tick()
        ).disposition == "quiet"
    else:
        assert first.disposition == "staged" and first.new_wakes == 1
        assert len(first.draft_ids) == len(first.action_ids) == 1
        await require_digest_pins(case, first.draft_ids[0], first.action_ids[0])
        published = await digest_native_counts(worker_tick_factory)
        assert published == tuple(value + 1 for value in before)
        for current in (worker, NotificationReadPreparationWorker(case.services, enabled=True)):
            replay = await current.tick()
            assert replay.disposition == "quiet" and replay.new_wakes == 0
            assert replay.replayed_wakes == 1 and not replay.draft_ids and not replay.action_ids
        assert await digest_native_counts(worker_tick_factory) == published
    ledger = await tick_ledger(worker_tick_factory)
    ledger.require_no_effects()
    assert case.native.catalog.models.models == ()
    assert case.saved.projection.accepted_task_ids == case.saved.projection.receipt_task_ids == ()
