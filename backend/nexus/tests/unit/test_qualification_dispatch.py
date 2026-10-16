"""Actual locked helpers plus supplied native-leaf/queue delivery; no DB or model calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid5

import pytest

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.execution.qualification_dispatch import QualificationDispatchService
from nexus.execution.qualification_service import PreparedQualification
from nexus.execution.runtime_contracts import ExecutionLease, ExecutionSnapshot
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore, next_segment_id
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.tests.unit.test_qualification_contracts import NOW
from nexus.tests.unit.test_qualification_service import Rows, delivery


async def case(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    Rows,
    PreparedQualification,
    CompanyControlScope,
    VerifiedIdentity,
    ExecutionStore,
    QualificationDispatchService,
    dict[str, int],
]:
    from nexus.execution import qualification_dispatch as module
    from nexus.execution.qualification_service import QualificationPreparationService

    rows, recipe, scope, identity = await delivery()
    preparation = QualificationPreparationService(rows.factory, (recipe,))
    prepared = await preparation.prepare_qualification(scope, identity, recipe.recipe_id)
    ledger = LedgerScope(
        company_id=scope.company_id,
        principal_id=identity.principal_id,
        task_id=prepared.request.task_id,
        trace_id=prepared.request.trace_id,
    )
    await CompanyJournal(rows.factory).approve_registered(
        ledger, prepared.request.action_id, prepared.action.proposal_hash, NOW, identity=identity
    )
    execution = ExecutionStore(rows.factory)
    calls = {"claim": 0, "wait": 0, "release": 0, "enqueue": 0}
    work = cast(ExecutionWork, rows.rows[ExecutionWork])

    async def claim(*args: object, **kwargs: object) -> ExecutionLease:
        calls["claim"] += 1
        work.segment_id = next_segment_id(snapshot(work))
        work.segment_number += 1
        work.fence += 1
        work.worker_id = UUID(int=88)
        work.lease_principal_id = identity.principal_id
        work.lease_until = NOW + timedelta(seconds=15)
        work.lease_mode = "execute"
        return ExecutionLease(
            company_id=work.company_id,
            task_id=work.task_id,
            trace_id=work.trace_id,
            actor_id=work.actor_id,
            workspace_id=work.workspace_id,
            run_id=work.run_id,
            workflow_version=work.workflow_version,
            segment_id=work.segment_id,
            worker_id=work.worker_id,
            fence=work.fence,
            expires_at=work.lease_until,
            mode="execute",
        )

    async def wait(*args: object, **kwargs: object) -> ExecutionSnapshot:
        calls["wait"] += 1
        work.state = "awaiting_approval"
        work.waiting_action_id = prepared.request.action_id
        work.fence += 1
        work.worker_id = work.lease_principal_id = work.lease_until = work.lease_mode = None
        return snapshot(work)

    async def release(*args: object, **kwargs: object) -> ExecutionSnapshot:
        calls["release"] += 1
        work.fence += 1
        work.worker_id = work.lease_principal_id = work.lease_until = work.lease_mode = None
        return snapshot(work)

    async def enqueue(*args: object, **kwargs: object) -> None:
        calls["enqueue"] += 1

    monkeypatch.setattr(execution, "claim", claim)
    monkeypatch.setattr(execution, "await_approval", wait)
    # Retirement uses this original factory-bound store, never a replacement factory.
    monkeypatch.setattr(ExecutionStore, "release", release)
    monkeypatch.setattr(module, "_enqueue_exact", enqueue)
    service = module.QualificationDispatchService(preparation, execution)
    return rows, prepared, scope, identity, execution, service, calls


@pytest.mark.parametrize("state", ["eligible", "verifying"])
async def test_stage_then_atomic_dispatch_and_duplicate_returns_exact_binding(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    rows, ready, scope, identity, _, service, calls = await case(monkeypatch)
    cast(ExecutionWork, rows.rows[ExecutionWork]).state = state
    end = clock_us() + 30_000_000
    first = await service.dispatch(
        scope, identity, ready.request.action_id, ready.action.proposal_hash, end_us=end
    )
    second = await service.dispatch(
        scope, identity, ready.request.action_id, ready.action.proposal_hash, end_us=end
    )
    assert first.disposition == "enqueued" and second.disposition == "existing"
    assert first.command == second.command and first.workflow_id == second.workflow_id
    assert calls == {"claim": 1, "wait": 1, "release": 0, "enqueue": 1}
    assert cast(ExecutionWork, rows.rows[ExecutionWork]).model_requests_used == 0
    assert cast(CostHold, rows.rows[CostHold]).amount_usd == ready.quote.amount_usd
    assert not service.pending_owners()


async def test_queue_failure_rolls_back_authorization_hold_and_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.execution import qualification_dispatch as module
    from nexus.execution.dispatch_models import SegmentDispatch

    rows, ready, scope, identity, _, service, _ = await case(monkeypatch)
    monkeypatch.setattr(
        module, "_enqueue_exact", AsyncMock(side_effect=ValueError("supplied SQL failure"))
    )
    with pytest.raises(ValueError):
        await service.dispatch(
            scope,
            identity,
            ready.request.action_id,
            ready.action.proposal_hash,
            end_us=clock_us() + 30_000_000,
        )
    assert cast(JournalAction, rows.rows[JournalAction]).consumed_at is None
    assert CostHold not in rows.rows and SegmentDispatch not in rows.rows
    assert cast(ExecutionWork, rows.rows[ExecutionWork]).state == "awaiting_approval"


@pytest.mark.parametrize("fault", ["hash", "waiting", "lease", "unknown", "expired"])
async def test_staging_denials_issue_no_native_leaf_or_hold(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    rows, ready, scope, identity, _, service, calls = await case(monkeypatch)
    work = cast(ExecutionWork, rows.rows[ExecutionWork])
    if fault == "waiting":
        work.state = "awaiting_approval"
        work.waiting_action_id = uuid5(work.run_id, "different")
    elif fault == "lease":
        work.worker_id = UUID(int=999)
        work.lease_until = NOW + timedelta(seconds=15)
    elif fault == "unknown":
        rows.rows[EffectIntent] = EffectIntent(state="outcome_unknown")
    with pytest.raises((ValueError, TimeoutError)):
        await service.dispatch(
            scope,
            identity,
            ready.request.action_id,
            "0" * 64 if fault == "hash" else ready.action.proposal_hash,
            end_us=clock_us() - 1 if fault == "expired" else clock_us() + 30_000_000,
        )
    assert calls == {"claim": 0, "wait": 0, "release": 0, "enqueue": 0}
    assert CostHold not in rows.rows


async def test_cancelled_claim_retains_actual_leaf_then_only_retires_returned_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows, ready, scope, identity, execution, service, calls = await case(monkeypatch)
    original = cast(Callable[..., Awaitable[ExecutionLease]], execution.claim)
    entered, released = asyncio.Event(), asyncio.Event()

    async def blocked(*args: object, **kwargs: object) -> ExecutionLease:
        entered.set()
        await released.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(execution, "claim", blocked)
    task = asyncio.create_task(
        service.dispatch(
            scope,
            identity,
            ready.request.action_id,
            ready.action.proposal_hash,
            end_us=clock_us() + 30_000_000,
        )
    )
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls["release"] == 0 and service.pending_owners()
    assert all(not owner.cancelled() for owner in service.pending_owners())
    released.set()
    _, pending = await asyncio.wait(service.pending_owners(), timeout=2)
    assert not pending and not service.pending_owners()
    assert calls == {"claim": 1, "wait": 0, "release": 1, "enqueue": 0}
    assert CostHold not in rows.rows


async def test_cancelled_wait_never_releases_while_actual_wait_leaf_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, ready, scope, identity, execution, service, calls = await case(monkeypatch)
    original = cast(Callable[..., Awaitable[ExecutionSnapshot]], execution.await_approval)
    entered, released = asyncio.Event(), asyncio.Event()

    async def blocked(*args: object, **kwargs: object) -> ExecutionSnapshot:
        entered.set()
        await released.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(execution, "await_approval", blocked)
    task = asyncio.create_task(
        service.dispatch(
            scope,
            identity,
            ready.request.action_id,
            ready.action.proposal_hash,
            end_us=clock_us() + 30_000_000,
        )
    )
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls["release"] == 0 and service.pending_owners()
    released.set()
    _, pending = await asyncio.wait(service.pending_owners(), timeout=2)
    assert not pending and calls["release"] == 0 and calls["enqueue"] == 0


async def test_matching_awaiting_action_dispatches_without_new_staging_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows, ready, scope, identity, _, service, calls = await case(monkeypatch)
    work = cast(ExecutionWork, rows.rows[ExecutionWork])
    work.state = "awaiting_approval"
    work.waiting_action_id = ready.request.action_id
    await service.dispatch(
        scope,
        identity,
        ready.request.action_id,
        ready.action.proposal_hash,
        end_us=clock_us() + 30_000_000,
    )
    assert calls == {"claim": 0, "wait": 0, "release": 0, "enqueue": 1}


async def test_original_end_after_queue_delivery_rolls_back_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.execution import qualification_dispatch as module
    from nexus.execution.dispatch_models import SegmentDispatch

    rows, ready, scope, identity, _, service, _ = await case(monkeypatch)
    end = clock_us() + 30_000_000

    async def expire(*args: object, **kwargs: object) -> None:
        monkeypatch.setattr(module, "clock_us", lambda: end)

    monkeypatch.setattr(module, "_enqueue_exact", expire)
    with pytest.raises(TimeoutError):
        await service.dispatch(
            scope, identity, ready.request.action_id, ready.action.proposal_hash, end_us=end
        )
    assert CostHold not in rows.rows and SegmentDispatch not in rows.rows
    assert cast(JournalAction, rows.rows[JournalAction]).consumed_at is None
