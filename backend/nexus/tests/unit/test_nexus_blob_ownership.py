"""Real finite protected files/blocked thread: caller cancellation must retain the actual leaf."""

import asyncio
import threading
from pathlib import Path

import pytest

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.tests.unit.nexus_cycle_fixture import key


async def test_cancelled_protected_read_retains_actual_thread_until_controlled_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    raw = b"actual protected Nexus file"
    reference = ArtifactRevisionRef(
        company_id=key("blob-company"),
        artifact_id=key("blob-artifact"),
        artifact_revision_id=key("blob-revision"),
        revision="r1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    store = ProtectedBlobStore(tmp_path / "blobs", storage_symbol="nexus.component.blobs")
    await store.save(reference, raw)
    entered, finish, finished = threading.Event(), threading.Event(), threading.Event()
    original = store._read

    def delayed(path: Path) -> bytes:
        entered.set()
        assert finish.wait(3), "finite thread explicitly released"
        try:
            return original(path)
        finally:
            finished.set()

    monkeypatch.setattr(store, "_read", delayed)
    caller = asyncio.create_task(store.read(reference))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        caller.cancel("original protected-read caller")
        with pytest.raises(asyncio.CancelledError, match="original protected-read caller"):
            await caller
        owners = getattr(store, "pending_owners", lambda: ())()
        assert owners and all(not task.cancelled() for task in owners)
    finally:
        finish.set()
        assert await asyncio.to_thread(finished.wait, 2)
        await asyncio.gather(
            *getattr(store, "pending_owners", lambda: ())(), return_exceptions=True
        )
    assert not store.pending_owners()


async def test_cancelled_save_retains_actual_write_without_adopting_a_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    raw = b"actual finite write"
    artifact = ArtifactRevisionRef(
        company_id=key("save-company"),
        artifact_id=key("save-artifact"),
        artifact_revision_id=key("save-revision"),
        revision="r1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    store = ProtectedBlobStore(tmp_path / "save", storage_symbol="nexus.unit.blobs")
    entered, finish, finished = threading.Event(), threading.Event(), threading.Event()
    original = store._path

    def delayed(value: ArtifactRevisionRef) -> Path:
        entered.set()
        assert finish.wait(3)
        try:
            return original(value)
        finally:
            finished.set()

    monkeypatch.setattr(store, "_path", delayed)
    caller = asyncio.create_task(store.save(artifact, raw))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        caller.cancel("original save cancellation")
        with pytest.raises(asyncio.CancelledError, match="original save cancellation"):
            await caller
        assert store.pending_owners() and all(not t.cancelled() for t in store.pending_owners())
    finally:
        finish.set()
        assert await asyncio.to_thread(finished.wait, 2)
        await asyncio.gather(*store.pending_owners(), return_exceptions=True)
    monkeypatch.setattr(store, "_path", original)
    assert await store.read(artifact) == raw and not store.pending_owners()


@pytest.mark.parametrize("expired", [False, True])
async def test_report_cancel_retains_leaf_before_release_and_never_clears_expired_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    from unittest.mock import AsyncMock

    from nexus.company.contracts.actions import ActionProposal
    from nexus.execution import native_report_worker as worker
    from nexus.execution import nexus_report_history as history
    from nexus.execution.dbos_contracts import SegmentCommand
    from nexus.execution.native_report_context import NativeReportContext
    from nexus.tests.unit.nexus_intent_fixture import boundary
    from nexus.tests.unit.nexus_report_fixture import credentials, services

    value = boundary(3)
    configured = services(value, value.install(monkeypatch))
    admission = value.catalog.nexus_cycle_admission
    assert admission is not None
    witness = await credentials(admission.slots[3].child.binding).current()
    command = SegmentCommand(
        company_id=value.work.company_id,
        task_id=value.work.task_id,
        trace_id=value.work.trace_id,
        run_id=value.work.run_id,
        actor_id=value.work.actor_id,
        workspace_id=value.work.workspace_id,
        action_id=value.action.id,
        segment_id=value.lease.segment_id,
    )
    clock = [1_000_000]
    monkeypatch.setattr(worker, "clock_us", lambda: clock[0])
    context = NativeReportContext(
        configured,
        command,
        ActionProposal.model_validate_json(value.action.proposal_json),
        value.identity,
        value.lease,
        witness,
        configured.report_credentials[0][1],
        2_000_000,
    )
    entered, finish = asyncio.Event(), asyncio.Event()
    leafs = []

    async def leaf() -> None:
        entered.set()
        await finish.wait()

    async def effect(actual: NativeReportContext) -> None:
        assert actual is context
        task = asyncio.create_task(leaf())
        configured._nexus_owners.append(task)
        leafs.append(task)
        await asyncio.shield(task)
        raise AssertionError("Cancelled chain must not continue after actual leaf")

    release = AsyncMock()
    monkeypatch.setattr(history, "read_nexus_report_history", AsyncMock(return_value=None))
    monkeypatch.setattr(worker, "prepare_context", AsyncMock(return_value=context))
    monkeypatch.setattr(worker, "run_native_effect", effect)
    monkeypatch.setattr(configured.execution, "release", release)
    caller = asyncio.create_task(
        worker.execute_native_report(configured, command, workflow_id=command.workflow_id)
    )
    await entered.wait()
    caller.cancel("original report caller")
    with pytest.raises(asyncio.CancelledError, match="original report caller"):
        await caller
    release.assert_not_awaited()
    assert configured.pending_owners() and not leafs[0].cancelled()
    if expired:
        clock[0] = 2_000_000
    finish.set()
    await asyncio.gather(*configured.pending_owners(), return_exceptions=True)
    if expired:
        release.assert_not_awaited()
    else:
        release.assert_awaited_once_with(value.lease, value.identity, blocked=True)
    assert not configured.pending_owners()
