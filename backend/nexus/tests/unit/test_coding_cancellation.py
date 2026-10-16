"""Cancellation stops subsequent private phases; real admitted FS leaves stay owned.

Actual H/TinyGit/private files and genuine witnesses are exercised. Native/source
SQL is supplied by the existing finite fixtures; no effect permit is issued.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

import httpx2
import pytest

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.planning_native_facts import clock_us
from nexus.execution.coding_operation import CodingOperation
from nexus.tests.unit.coding_runtime_fixture import services_from_store
from nexus.tests.unit.test_coding_candidate_reader import candidate_case
from nexus.tests.unit.test_coding_intent import witness
from nexus.tests.unit.test_coding_prepared_store import NativeDelivery, store_case


@dataclass
class FirstBlobPhase:
    """Block one actual filesystem callable; observe later admissions without replacing IO."""

    entered: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    caller_stopped: bool = False
    phases_after_stop: list[bool] = field(default_factory=list)

    def install(self, blobs: ProtectedBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
        original = blobs._owned

        async def delayed[T](call: Callable[[], T]) -> T:
            first = not self.phases_after_stop
            self.phases_after_stop.append(self.caller_stopped)

            def held() -> T:
                if first:
                    self.entered.set()
                    if not self.release.wait(5):
                        raise AssertionError("Actual private leaf was not released")
                return call()

            return await original(held)

        monkeypatch.setattr(blobs, "_owned", delayed)

    async def wait(self) -> None:
        async with asyncio.timeout(10):
            while not self.entered.is_set():
                await asyncio.sleep(0.005)


async def settled(owners: tuple[asyncio.Task[object], ...]) -> None:
    """Settlement observation never cancels actual admitted resources."""
    async with asyncio.timeout(10):
        await asyncio.gather(*(asyncio.shield(owner) for owner in owners), return_exceptions=True)


async def test_cancelled_save_keeps_first_blob_owned_but_stops_later_private_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, prepared, lease = store_case(tmp_path)
    credential = await witness(prepared)
    NativeDelivery(store, prepared).install(monkeypatch)
    services = services_from_store(
        tmp_path, store, prepared, lease, httpx2.MockTransport(lambda _: httpx2.Response(500))
    )
    operation = CodingOperation(services, "cancel-save", clock_us() + 20_000_000)
    operation.credential = credential
    operation._store = store
    services._stores.append(store)
    phase = FirstBlobPhase()
    phase.install(store.blobs, monkeypatch)
    task = asyncio.create_task(
        operation.call(store.save_worker(lease, credential, prepared, end_us=operation.end))
    )
    try:
        await phase.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        phase.caller_stopped = True
        assert operation.pending_owners()
    finally:
        phase.release.set()
        await settled(operation.pending_owners())
        operation.finish()
    assert not any(phase.phases_after_stop)
    assert not operation.pending_owners()
    assert store._stopped


async def test_cancelled_candidate_stops_input_pipeline_and_allows_next_owner_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = await candidate_case(tmp_path, monkeypatch)
    phase = FirstBlobPhase()
    phase.install(f.owner.services.prepared_blobs, monkeypatch)
    task = asyncio.create_task(
        f.reader.read(
            f.owner.scope,
            f.owner.owner,
            f.owner.row.id,
            expected_current_revision_id=f.owner.prepared.binding.plan.plan_revision_id,
            end_us=clock_us() + 20_000_000,
        )
    )
    try:
        await phase.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        phase.caller_stopped = True
        assert f.reader.pending_owners()
    finally:
        phase.release.set()
        await settled(f.reader.pending_owners())
    assert not any(phase.phases_after_stop)
    assert not f.reader.pending_owners()
    assert not f.reader._stopped
    assert not f.reader.inputs._stopped
    phase.caller_stopped = False
    read = await f.reader.read(
        f.owner.scope,
        f.owner.owner,
        f.owner.row.id,
        expected_current_revision_id=f.owner.prepared.binding.plan.plan_revision_id,
        end_us=clock_us() + 20_000_000,
    )
    assert read.value.action_id == f.owner.row.id
    assert not f.reader.pending_owners()
