"""Finite worker composition and actual pending-task ownership; no queue or SDK launch."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.notifications.worker_identity import _verified_witness
from nexus.core.llm.qualification_contracts import APPLICATION, QUEUE, VERSION, WORKFLOW
from nexus.execution import qualification_worker as module
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.effect_store import EffectStore
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.qualification_worker_context import (
    QualificationContext,
    QualificationOperation,
)
from nexus.execution.qualification_worker_services import QualificationWorkerServices
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.qualification_client import QualificationRunResult
from nexus.tests.unit.test_qualification_client import prepared
from nexus.tests.unit.test_qualification_contracts import NOW, scope


def services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[QualificationWorkerServices, QualificationContext]:
    client, _ = prepared(tmp_path, monkeypatch)
    identities = AsyncMock()
    witness = _verified_witness(
        client._identity, NOW - timedelta(seconds=1), NOW + timedelta(minutes=5)
    )
    identities.current.return_value = witness
    command = SegmentCommand(
        company_id=client._lease.company_id,
        task_id=client._lease.task_id,
        trace_id=client._lease.trace_id,
        actor_id=client._lease.actor_id,
        workspace_id=client._lease.workspace_id,
        run_id=client._lease.run_id,
        action_id=client._request.action_id,
        segment_id=client._lease.segment_id,
    )
    factory = cast(async_sessionmaker[AsyncSession], MagicMock())
    value = QualificationWorkerServices(
        factory,
        ExecutionStore(factory),
        EffectStore(factory),
        QualificationPreparationService(factory, (client._recipe,)),
        identities,
        client._resolver,
        client._store,
        client._lease.worker_id,
        WorkflowRegistration(
            workflow_name=WORKFLOW,
            workflow_version=VERSION,
            queue_name=QUEUE,
            application_name=APPLICATION,
        ),
    )
    return value, QualificationContext(
        command, scope(), witness, client._recipe, client._request, "f" * 64, None
    )


def test_fixed_queue_and_original_factory_cannot_be_spliced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = services(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        replace(value, registration=value.registration.model_copy(update={"queue_name": "other"}))
    value.effects._factory = cast(async_sessionmaker[AsyncSession], object())
    with pytest.raises(ValueError):
        value.require_composition()


async def test_operation_keeps_actual_leaf_after_cancellation_and_never_cancels_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = services(tmp_path, monkeypatch)
    operation = QualificationOperation(value)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def leaf() -> int:
        entered.set()
        await finish.wait()
        return 7

    caller = asyncio.create_task(operation.call(leaf()))
    await entered.wait()
    caller.cancel("actual first caller")
    with pytest.raises(asyncio.CancelledError, match="actual first caller"):
        await caller
    assert len(operation.pending_owners()) == 1
    actual = operation.pending_owners()[0]
    assert not actual.cancelled()
    finish.set()
    await operation.settle()
    assert not operation.pending_owners() and actual.result() == 7


async def test_completed_native_replay_skips_acquire_client_and_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, context = services(tmp_path, monkeypatch)
    (tmp_path / "actual").mkdir()
    client, _ = prepared(tmp_path / "actual", monkeypatch)
    outcome = await client.request_once()
    assert outcome.record is not None
    context = replace(context, issued=outcome.record)
    monkeypatch.setattr(module, "read_context", AsyncMock(return_value=context))
    acquire = AsyncMock(side_effect=AssertionError("no replay acquisition"))
    monkeypatch.setattr(module, "acquire_context", acquire)
    monkeypatch.setattr(module, "recover_issued", AsyncMock(return_value=outcome))
    result = await module.execute_qualification_segment(
        value, context.command, workflow_id=context.command.workflow_id
    )
    assert result.status == "observed" and result.replayed and not result.lease_released
    acquire.assert_not_called()
    assert not value._operations and not value.pending_owners()


async def test_release_waits_actual_client_resource_and_preserves_first_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, context = services(tmp_path, monkeypatch)
    client, _ = prepared(tmp_path / "actual", monkeypatch)
    entered, retire = asyncio.Event(), asyncio.Event()
    order: list[str] = []

    async def resource() -> None:
        entered.set()
        await retire.wait()
        order.append("resource-settled")

    async def acquire(operation: QualificationOperation, current: QualificationContext) -> int:
        operation.identity = current.credential.identity
        operation.lease = client._lease
        return operation.end - 5_000_000

    async def request_once() -> QualificationRunResult:
        task = asyncio.create_task(resource())
        client._owners.append(cast(asyncio.Task[object], task))
        await entered.wait()
        raise ValueError("first actual qualification failure")

    async def release(*args: object, **kwargs: object) -> object:
        assert not client.pending_owners()
        order.append("release")
        return object()

    monkeypatch.setattr(module, "read_context", AsyncMock(return_value=context))
    monkeypatch.setattr(module, "acquire_context", acquire)
    monkeypatch.setattr(module, "refresh_issued", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "QualificationClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(client, "request_once", request_once)
    monkeypatch.setattr(value.execution, "release", release)
    running = asyncio.create_task(
        module.execute_qualification_segment(
            value,
            context.command,
            workflow_id=context.command.workflow_id,
        )
    )
    await entered.wait()
    await asyncio.sleep(0)
    assert order == [] and not running.done()
    retire.set()
    result = await running
    assert order == ["resource-settled", "release"]
    assert result.error_type == "ValueError" and result.status == "blocked"
    assert result.lease_released and not result.resources_pending


async def test_original_end_retains_pending_owner_and_denies_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.harness import qualification_evidence

    value, _ = services(tmp_path, monkeypatch)
    operation = QualificationOperation(value)
    finish = asyncio.Event()
    pending = asyncio.create_task(finish.wait())
    operation.owners.append(cast(asyncio.Task[object], pending))
    monkeypatch.setattr(qualification_evidence, "clock_us", lambda: operation.end)
    monkeypatch.setattr(
        "nexus.execution.qualification_worker_context.clock_us", lambda: operation.end
    )
    try:
        await module._release(operation)
        assert operation.pending_owners() == (pending,) and not pending.cancelled()
        assert not operation.released
    finally:
        finish.set()
        await pending
