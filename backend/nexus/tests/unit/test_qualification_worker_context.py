"""Exact original acquisition and credential bounds over supplied native store leaves."""

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.notifications.worker_identity import _verified_witness
from nexus.core.llm.qualification_contracts import APPLICATION, QUEUE, VERSION, WORKFLOW
from nexus.execution import qualification_worker_context as module
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.effect_store import EffectStore
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.qualification_worker_context import (
    QualificationOperation,
    acquire_context,
    read_context,
)
from nexus.execution.qualification_worker_services import QualificationWorkerServices
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.qualification_evidence import FileQualificationEvidenceStore
from nexus.tests.unit.test_qualification_client import prepared
from nexus.tests.unit.test_qualification_contracts import NOW
from nexus.tests.unit.test_qualification_service import delivery
from nexus.tests.unit.test_qualification_worker import services


async def test_actual_acquired_lease_remains_owned_if_final_credential_check_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, context = services(tmp_path, monkeypatch)
    client, _ = prepared(tmp_path / "actual", monkeypatch)
    operation = QualificationOperation(value)
    monkeypatch.setattr(
        value.execution, "recover_dispatched", AsyncMock(return_value=client._lease)
    )
    monkeypatch.setattr(module, "db_now", AsyncMock(return_value=NOW + timedelta(hours=1)))
    with pytest.raises(ValueError):
        await acquire_context(operation, context)
    assert operation.lease == client._lease and operation.lease_task is not None
    assert operation.lease_task.done() and not operation.lease_task.cancelled()


async def test_first_actual_lease_task_is_retained_on_caller_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, context = services(tmp_path, monkeypatch)
    client, _ = prepared(tmp_path / "actual", monkeypatch)
    operation = QualificationOperation(value)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def claim(*args: object, **kwargs: object) -> object:
        entered.set()
        await finish.wait()
        return client._lease

    monkeypatch.setattr(value.execution, "recover_dispatched", claim)
    caller = asyncio.create_task(acquire_context(operation, context))
    await entered.wait()
    caller.cancel("first acquisition cancellation")
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert operation.lease is None and operation.lease_task is not None
    assert not operation.lease_task.cancelled()
    finish.set()
    await operation.settle()
    assert operation.lease == client._lease and not operation.pending_owners()


async def test_real_preparation_dispatch_and_catalog_selector_composition(
    tmp_path: Path,
) -> None:
    rows, recipe, owner_scope, identity = await delivery()
    preparation = QualificationPreparationService(rows.factory, (recipe,))
    actual = await preparation.prepare_qualification(owner_scope, identity, recipe.recipe_id)
    registered = actual.work.registration
    command = SegmentCommand(
        company_id=owner_scope.company_id,
        task_id=registered.work.task_id,
        trace_id=registered.work.trace_id,
        actor_id=identity.principal_id,
        workspace_id=identity.workspace_id,
        run_id=registered.run_id,
        action_id=actual.action.proposal.action_id,
        segment_id=UUID(int=999),
    )
    dispatch = SegmentDispatch(
        company_id=command.company_id,
        action_id=command.action_id,
        task_id=command.task_id,
        run_id=command.run_id,
        segment_id=command.segment_id,
        workflow_id=command.workflow_id,
        binding_json=command.model_dump_json(),
    )
    rows.rows[SegmentDispatch] = dispatch
    identities = AsyncMock()
    identities.current.return_value = _verified_witness(
        identity,
        NOW - timedelta(seconds=1),
        NOW + timedelta(minutes=5),
    )
    value = QualificationWorkerServices(
        rows.factory,
        ExecutionStore(rows.factory),
        EffectStore(rows.factory),
        preparation,
        identities,
        AsyncMock(),
        FileQualificationEvidenceStore(tmp_path / "evidence"),
        UUID(int=888),
        WorkflowRegistration(
            workflow_name=WORKFLOW,
            workflow_version=VERSION,
            queue_name=QUEUE,
            application_name=APPLICATION,
        ),
    )
    context = await read_context(
        QualificationOperation(value), command, workflow_id=command.workflow_id
    )
    assert context.recipe == recipe and context.request == actual.request
    assert context.issued is None and context.proposal_hash == actual.action.proposal_hash
    dispatch.binding_json = command.model_copy(
        update={"segment_id": UUID(int=998)}
    ).model_dump_json()
    with pytest.raises(ValueError):
        await read_context(QualificationOperation(value), command, workflow_id=command.workflow_id)


async def test_original_expiry_denies_unstarted_native_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.harness import qualification_evidence

    value, _ = services(tmp_path, monkeypatch)
    operation = QualificationOperation(value)
    leaf = AsyncMock()
    monkeypatch.setattr(qualification_evidence, "clock_us", lambda: operation.end)
    with pytest.raises(TimeoutError):
        await operation.call(leaf())
    leaf.assert_not_awaited()
    assert not operation.pending_owners()


async def test_client_end_uses_actual_credential_remaining_and_preawait_clock_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from nexus.harness import qualification_evidence

    value, context = services(tmp_path, monkeypatch)
    client, _ = prepared(tmp_path / "actual", monkeypatch)
    context = replace(
        context,
        credential=_verified_witness(
            context.credential.identity,
            NOW - timedelta(seconds=1),
            NOW + timedelta(seconds=3),
        ),
    )
    now = [1_000_000]
    monkeypatch.setattr(module, "clock_us", lambda: now[0])
    monkeypatch.setattr(qualification_evidence, "clock_us", lambda: now[0])
    operation = QualificationOperation(value)
    native_lease = client._lease.model_copy(update={"expires_at": NOW + timedelta(seconds=60)})
    claimed = AsyncMock(return_value=native_lease)
    monkeypatch.setattr(value.execution, "recover_dispatched", claimed)

    async def clock(*args: object) -> object:
        now[0] = 2_000_000
        return NOW

    monkeypatch.setattr(module, "db_now", clock)
    end = await acquire_context(operation, context)
    assert end == 4_000_000  # Before-await1s +actual3s; never after-await2s +3s.
    assert claimed.call_args.kwargs["ttl_seconds"] == 60
