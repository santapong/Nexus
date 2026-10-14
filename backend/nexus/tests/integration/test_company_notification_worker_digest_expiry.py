"""Finite actual digest registration closes the three staging transaction final clocks."""

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.tests.notification_worker_digest_expiry_support import (
    DigestExpiryObservation,
    finite_digest_case,
    nominate_digest_final_clock,
    prepare_digest_stage,
)
from nexus.tests.notification_worker_digest_fixture import worker_digest_case
from nexus.tests.notification_worker_tick_fixture import worker_tick_factory
from nexus.tests.notification_worker_tick_matrix_support import tick_ledger

__all__ = ["worker_tick_factory"]


@pytest.mark.parametrize("phase", ["emitter", "consumer", "preparation"])
async def test_actual_digest_expiry_closes_selected_stage_final_clock(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    record_property: Callable[[str, object], None],
) -> None:
    original = await worker_digest_case(worker_tick_factory, tmp_path, "weekly")
    assert original.window is not None
    case = await finite_digest_case(original, tmp_path)
    await prepare_digest_stage(case, tmp_path, phase)
    before = await tick_ledger(worker_tick_factory)
    assert before.publication[2:4] == ((1, 1) if phase == "preparation" else (0, 0))
    assert len(before.journal_ids) == 1
    seen: list[DigestExpiryObservation] = []
    nominate_digest_final_clock(monkeypatch, case, phase, seen)
    error = BrainDeniedError if phase == "emitter" else NotificationUnavailableError
    with pytest.raises(error):
        await NotificationReadPreparationWorker(case.services, enabled=True).tick()
    assert len(seen) == 1 and seen[0].before < case.registration.expires_at <= seen[0].after
    assert await tick_ledger(worker_tick_factory) == before
    before.require_no_effects()
    record_property("phase", phase)
    record_property("actual_registration_expiry", case.registration.expires_at.isoformat())
    record_property("actual_before", seen[0].before.isoformat())
    record_property("actual_after", seen[0].after.isoformat())
    record_property("alias_calls", seen[0].alias_calls)
    record_property("prior_publication", str(before.publication))
