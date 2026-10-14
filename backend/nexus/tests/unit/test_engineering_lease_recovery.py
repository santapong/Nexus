"""Only exact live prior acquisition waits; effects and credentials are never retried/refreshed."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_lease_recovery import recover_engineering_lease
from nexus.execution.engineering_worker_services import EngineeringWorkerServices
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.unit.test_company_management_contracts import binding
from nexus.tests.unit.test_company_notification_worker_identity import adapter, signed


async def inputs() -> tuple[
    Any, LedgerScope, AuthenticatedWorkerIdentity, SegmentCommand, ExecutionLease
]:
    # The first fixture value is a controlled SimpleNamespace of AsyncMock methods;
    # production services remain typed and their actual locked preflight is tested separately.
    actual = binding()
    credential = await adapter(signed())[0].current(actual)
    command = SegmentCommand(
        company_id=actual.company_id,
        task_id=actual.task_id,
        trace_id=actual.trace_id,
        actor_id=actual.actor_id,
        workspace_id=actual.workspace_id,
        run_id=actual.run_id,
        action_id=UUID(int=97),
        segment_id=UUID(int=98),
    )
    scope = LedgerScope(
        company_id=actual.company_id,
        principal_id=actual.actor_id,
        task_id=actual.task_id,
        trace_id=actual.trace_id,
    )
    lease = ExecutionLease(
        company_id=actual.company_id,
        task_id=actual.task_id,
        trace_id=actual.trace_id,
        actor_id=actual.actor_id,
        workspace_id=actual.workspace_id,
        run_id=actual.run_id,
        workflow_version="v1",
        segment_id=command.segment_id,
        worker_id=UUID(int=99),
        fence=2,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
        mode="reconcile",
    )
    execution = SimpleNamespace(
        recover_dispatched=AsyncMock(return_value=lease), release=AsyncMock()
    )
    services = cast(
        EngineeringWorkerServices,
        SimpleNamespace(
            factory=object(),
            runner=SimpleNamespace(execution=execution),
            worker_id=lease.worker_id,
            lease_ttl_seconds=60,
        ),
    )
    return services, scope, credential, command, lease


async def test_waits_for_live_prior_then_acquires_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import nexus.execution.engineering_lease_recovery as module

    services, scope, credential, command, lease = await inputs()
    prior = AsyncMock(side_effect=[datetime.now(UTC) + timedelta(seconds=0.01), None])
    monkeypatch.setattr(module, "prior_live_deadline", prior)
    monkeypatch.setattr(module, "require_current_credential", AsyncMock())
    assert await recover_engineering_lease(services, scope, credential, command) == lease
    assert services.runner.execution.recover_dispatched.await_count == 1
    assert prior.await_count == 2


async def test_permanent_preflight_denial_does_not_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    import nexus.execution.engineering_lease_recovery as module

    services, scope, credential, command, _ = await inputs()
    monkeypatch.setattr(
        module,
        "prior_live_deadline",
        AsyncMock(side_effect=ExecutionDeniedError("Foreign segment")),
    )
    with pytest.raises(ExecutionDeniedError):
        await recover_engineering_lease(services, scope, credential, command)
    assert services.runner.execution.recover_dispatched.await_count == 0


async def test_cancellation_while_waiting_propagates_without_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.execution.engineering_lease_recovery as module

    services, scope, credential, command, _ = await inputs()
    monkeypatch.setattr(
        module,
        "prior_live_deadline",
        AsyncMock(return_value=datetime.now(UTC) + timedelta(seconds=10)),
    )
    reached = asyncio.Event()

    async def waiting(seconds: float) -> None:
        reached.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(module, "wait_prior", waiting)
    task = asyncio.create_task(recover_engineering_lease(services, scope, credential, command))
    await reached.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert services.runner.execution.recover_dispatched.await_count == 0


async def test_total_wait_timeout_is_finite_without_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.execution.engineering_lease_recovery as module

    services, scope, credential, command, _ = await inputs()
    monkeypatch.setattr(module, "MAX_ACQUISITION_SECONDS", 0.01)
    monkeypatch.setattr(
        module,
        "prior_live_deadline",
        AsyncMock(return_value=datetime.now(UTC) + timedelta(seconds=10)),
    )
    with pytest.raises(ExecutionDeniedError, match="bounded acquisition"):
        await recover_engineering_lease(services, scope, credential, command)
    assert services.runner.execution.recover_dispatched.await_count == 0


async def test_expiry_after_acquisition_releases_exact_new_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.execution.engineering_lease_recovery as module

    services, scope, credential, command, lease = await inputs()
    monkeypatch.setattr(module, "prior_live_deadline", AsyncMock(return_value=None))
    monkeypatch.setattr(
        module,
        "require_current_credential",
        AsyncMock(side_effect=ValueError("Credential expired")),
    )
    with pytest.raises(ValueError, match="expired"):
        await recover_engineering_lease(services, scope, credential, command)
    services.runner.execution.release.assert_awaited_once_with(lease, credential.identity)


async def test_permanent_acquisition_denial_with_no_live_prior_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.execution.engineering_lease_recovery as module

    services, scope, credential, command, _ = await inputs()
    monkeypatch.setattr(module, "prior_live_deadline", AsyncMock(return_value=None))
    services.runner.execution.recover_dispatched.side_effect = ExecutionDeniedError(
        "Actual source unavailable"
    )
    with pytest.raises(ExecutionDeniedError, match="source unavailable"):
        await recover_engineering_lease(services, scope, credential, command)
    assert services.runner.execution.recover_dispatched.await_count == 1


@pytest.mark.parametrize("fault", ["command", "segment", "member"])
async def test_real_preflight_never_waits_on_foreign_or_denied_scope(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from contextlib import asynccontextmanager

    import nexus.execution.engineering_lease_recovery as module
    from nexus.execution.runtime_models import ExecutionWork

    services, scope, credential, command, _ = await inputs()
    work = ExecutionWork(
        worker_id=UUID(int=44),
        segment_id=command.segment_id,
        lease_until=datetime.now(UTC) + timedelta(seconds=30),
    )

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[object, object, object]]:
        if fault == "member":
            raise ExecutionDeniedError("Current membership revoked")
        yield object(), object(), object()

    monkeypatch.setattr(module, "runtime_transaction", transaction)
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=work))
    actual = (
        command.model_copy(update={"action_id": UUID(int=999)}) if fault == "command" else command
    )
    monkeypatch.setattr(module, "dispatched_binding", AsyncMock(return_value=actual))
    monkeypatch.setattr(module, "db_now", AsyncMock(return_value=datetime.now(UTC)))
    monkeypatch.setattr(module, "require_wait_admission", AsyncMock())
    if fault == "segment":
        work.segment_id = UUID(int=998)
    with pytest.raises(ExecutionDeniedError):
        await module.prior_live_deadline(services, scope, credential, command)
    assert services.runner.execution.recover_dispatched.await_count == 0


async def test_internal_timeout_is_not_relabelled_acquisition_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.execution.engineering_lease_recovery as module

    services, scope, credential, command, _ = await inputs()
    monkeypatch.setattr(
        module, "prior_live_deadline", AsyncMock(side_effect=TimeoutError("Database timeout"))
    )
    with pytest.raises(TimeoutError, match="Database timeout"):
        await recover_engineering_lease(services, scope, credential, command)
    assert services.runner.execution.recover_dispatched.await_count == 0


async def test_cancellation_after_acquisition_releases_exact_new_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.execution.engineering_lease_recovery as module

    services, scope, credential, command, lease = await inputs()
    monkeypatch.setattr(module, "prior_live_deadline", AsyncMock(return_value=None))
    monkeypatch.setattr(
        module, "require_current_credential", AsyncMock(side_effect=asyncio.CancelledError())
    )
    with pytest.raises(asyncio.CancelledError):
        await recover_engineering_lease(services, scope, credential, command)
    services.runner.execution.release.assert_awaited_once_with(lease, credential.identity)


@pytest.mark.parametrize("kind", ["fresh_paused", "issued_splice", "other_unresolved"])
async def test_wait_admission_does_not_mask_permanent_fresh_or_issued_failures(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    # Keep the >50-line typed journal/intent fixture and fresh-vs-issued denial
    # together; the result must not depend on filtering away a conflicting record.
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

    import nexus.execution.engineering_lease_recovery as module
    from nexus.company.contracts.actions import ActionProposal
    from nexus.execution.runtime_models import EffectIntent, ExecutionWork
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_models import CompanyControl, JournalAction

    services, scope, credential, command, _ = await inputs()
    proposal = ActionProposal(
        company_id=command.company_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        actor_id=command.actor_id,
        action_id=command.action_id,
        revision=1,
        tool="company.builder.run.v1",
        tool_version="v1",
        resource="fixture",
        parameters={},
        policy_version="fixture",
        price_version="fixture",
        estimated_cost_usd=Decimal("0.01"),
    )
    action = JournalAction(
        proposal_json=proposal.model_dump_json(), proposal_hash=action_hash(proposal)
    )
    issued = (
        None
        if kind == "fresh_paused"
        else EffectIntent(
            task_id=command.task_id,
            trace_id=command.trace_id,
            run_id=UUID(int=999),
            proposal_hash=action.proposal_hash,
        )
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = [action, issued]
    scalar_rows = SimpleNamespace(all=lambda: [UUID(int=998)] if kind == "other_unresolved" else [])
    session.scalars.return_value = scalar_rows
    control = CompanyControl(paused=True)
    runtime = AsyncMock()
    management = AsyncMock()
    monkeypatch.setattr(module, "require_runtime_scope", runtime)
    monkeypatch.setattr(module, "require_management_execution", management)
    with pytest.raises(ExecutionDeniedError):
        await module.require_wait_admission(
            session, control, services, scope, credential.identity, command, ExecutionWork()
        )
    assert runtime.await_count == management.await_count == 0
