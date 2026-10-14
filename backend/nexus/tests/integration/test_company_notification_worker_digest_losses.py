"""Actual source/config loss denies; licensed stale immutable report is explicitly obsolete."""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.recipient_registry import RecipientConfigurationError
from nexus.company.notifications.worker_config import WorkerConfigurationError
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.notification_worker_digest_fixture import worker_digest_case
from nexus.tests.notification_worker_digest_loss_support import (
    current_digest_is_stale,
    emit_digest_wake,
    lose_worker_file_at_final_clock,
    record_licensed_obsolete,
    revise_actual_digest_source,
    revoke_actual_source_read,
)
from nexus.tests.notification_worker_tick_fixture import worker_tick_factory
from nexus.tests.notification_worker_tick_matrix_support import configure_worker, tick_ledger

__all__ = ["worker_tick_factory"]


async def test_actual_source_read_revoke_after_digest_wake_cannot_acknowledge(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await worker_digest_case(worker_tick_factory, tmp_path, "weekly")
    await emit_digest_wake(case)
    await revoke_actual_source_read(case)
    configure_worker(tmp_path, emit=False, consume=True, prepare=False)
    before = await tick_ledger(worker_tick_factory)
    # The actual sender charter covers this source; its current native admission denies first.
    with pytest.raises(ExecutionDeniedError):
        await NotificationReadPreparationWorker(case.services, enabled=True).tick()
    assert await tick_ledger(worker_tick_factory) == before
    before.require_no_effects()


async def test_owned_recipient_loss_after_digest_wake_has_no_body_or_ack(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await worker_digest_case(worker_tick_factory, tmp_path, "weekly")
    await emit_digest_wake(case)
    (tmp_path / "synthetic-worker-recipient.json").unlink()
    configure_worker(tmp_path, emit=False, consume=True, prepare=False)
    before = await tick_ledger(worker_tick_factory)
    with pytest.raises(RecipientConfigurationError):
        await NotificationReadPreparationWorker(case.services, enabled=True).tick()
    assert await tick_ledger(worker_tick_factory) == before
    before.require_no_effects()


async def test_owned_worker_file_loss_at_actual_emitter_final_clock_rolls_back_wake(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await worker_digest_case(worker_tick_factory, tmp_path, "weekly")
    configure_worker(tmp_path, emit=True, consume=False, prepare=False)
    before = await tick_ledger(worker_tick_factory)
    seen: list[int] = []
    lose_worker_file_at_final_clock(monkeypatch, tmp_path, seen)
    with pytest.raises(WorkerConfigurationError):
        await NotificationReadPreparationWorker(case.services, enabled=True).tick()
    assert seen == [2]
    assert await tick_ledger(worker_tick_factory) == before
    before.require_no_effects()


async def test_public_source_cas_revision_makes_saved_digest_stale_and_licensed_obsolete(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await worker_digest_case(worker_tick_factory, tmp_path, "weekly")
    old_wake = await emit_digest_wake(case)
    changed = await revise_actual_digest_source(case, tmp_path)
    assert changed.status == "accepted"
    await current_digest_is_stale(case)
    assert await emit_digest_wake(case, expected=False) is None
    configure_worker(tmp_path, emit=False, consume=True, prepare=False)
    before = await tick_ledger(worker_tick_factory)
    seen: list[UUID] = []
    assert old_wake is not None
    record_licensed_obsolete(monkeypatch, old_wake, seen)
    result = await NotificationReadPreparationWorker(case.services, enabled=True).tick()
    assert result.disposition == "quiet" and not result.draft_ids and not result.action_ids
    assert old_wake in seen
    after = await tick_ledger(worker_tick_factory)
    assert after.publication[:4] == before.publication[:4]
    assert after.publication[4] == after.publication[5]
    assert (
        after.journal_ids == before.journal_ids
        and after.journal_state_sha256 == before.journal_state_sha256
    )
    after.require_no_effects()
