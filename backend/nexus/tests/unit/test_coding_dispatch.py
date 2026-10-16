"""Fresh C dispatch cannot manufacture identity, input or approval from posted selectors."""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.builder.contained_query import clock_us
from nexus.execution.coding_dispatch import dispatch
from nexus.tests.unit.coding_runtime_fixture import runtime_case


@pytest.mark.parametrize("fault", ["hash", "actor", "workspace", "unregistered"])
async def test_posted_selector_cannot_read_or_authorize_c(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    value, prepared, _ = runtime_case(tmp_path)
    scope = prepared.scope
    if fault == "actor":
        scope = scope.model_copy(update={"principal_id": UUID(int=999), "actor_id": UUID(int=999)})
    elif fault == "workspace":
        scope = scope.model_copy(update={"workspace_id": UUID(int=999)})
    elif fault == "unregistered":
        scope = scope.model_copy(update={"task_id": None, "task_trace_id": None})
    from nexus.company.management.coding_prepared_store import CodingPreparedStore

    private = AsyncMock(side_effect=AssertionError("invalid selectors cannot read private input"))
    monkeypatch.setattr(CodingPreparedStore, "load_actor", private)
    with pytest.raises(ValueError):
        await dispatch(
            value,
            scope,
            prepared.request.action_id,
            "bad" if fault == "hash" else "a" * 64,
            end_us=clock_us() + 10_000_000,
        )
    private.assert_not_awaited()


@pytest.mark.parametrize("late_enqueue", [False, True])
async def test_actual_atomic_wrapper_keeps_control_transaction_and_original_enqueue_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    late_enqueue: bool,
) -> None:
    """Authorization/SQL leaves supplied; real wrapper must retain ordering and late denial."""
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal
    from types import SimpleNamespace
    from typing import cast
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
    from nexus.execution import coding_dispatch as module
    from nexus.execution.coding_context import CodingState
    from nexus.execution.coding_operation import CodingOperation
    from nexus.execution.coding_services import REGISTRATION
    from nexus.execution.dbos_contracts import SegmentCommand
    from nexus.execution.runtime_support import snapshot
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_budget import billing_day
    from nexus.harness.journal_contracts import ActionRecord
    from nexus.harness.journal_models import CompanyControl, CostHold
    from nexus.harness.lifecycle import ActionState
    from nexus.harness.model_authorizer_contracts import model_action_parameters
    from nexus.tests.unit.coding_runtime_fixture import description, native_work

    value, prepared, lease = runtime_case(tmp_path)
    loaded = description(value, prepared)
    operation = CodingOperation(value, "dispatch-wrapper", clock_us() + 10_000_000)
    credential = await value.identities.current()
    operation.credential = credential
    work = native_work(value, lease)
    now = datetime.now(UTC)
    events = []
    active = False
    admission = value.management.catalog.nexus_coding_admission
    assert admission is not None
    control = CompanyControl(
        company_id=work.company_id,
        owner_id=admission.procedure.binding.actor_id,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(5),
    )
    quote = SimpleNamespace(amount_usd=Decimal("0.01"))
    resources = (loaded.reference.condition,)
    proposal = ActionProposal(
        company_id=work.company_id,
        action_id=prepared.request.action_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        actor_id=work.actor_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource="model:" + value.registry_id,
        parameters=model_action_parameters(prepared.request, value.recipe),
        preconditions=resources,
        policy_version="p1",
        price_version=prepared.request.price_version,
        estimated_cost_usd=Decimal("0.01"),
    )
    approval = ApprovalDecision(
        company_id=work.company_id,
        decision_id=UUID(int=901),
        action_id=proposal.action_id,
        action_revision=1,
        action_hash=action_hash(proposal),
        approver_id=control.owner_id,
        decision="approved",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(seconds=20),
    )
    original = ActionRecord(
        company_id=work.company_id,
        proposal=proposal,
        proposal_hash=action_hash(proposal),
        state=ActionState.AWAITING_APPROVAL,
        approval=approval,
        consumed_at=None,
    )
    hold = CostHold(
        action_id=proposal.action_id,
        company_id=work.company_id,
        task_id=work.task_id,
        amount_usd=Decimal("0.01"),
        actual_usd=None,
        state="held",
        day=billing_day(now),
    )
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(side_effect=lambda model, key: hold if model is CostHold else None)

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, MagicMock]]:
        nonlocal active
        active = True
        events.append("control-first")
        try:
            yield cast(AsyncSession, session), control, MagicMock()
        except BaseException:
            events.append("rollback")
            raise
        else:
            events.append("commit")
        finally:
            active = False

    async def fresh(*args: object) -> tuple[object, ...]:
        assert active
        events.append("fresh")
        return work, original, resources, quote

    async def authorize(*args: object) -> None:
        assert active
        events.append("authorize-hold")

    async def reserve(session: AsyncSession, command: SegmentCommand, **kwargs: object) -> None:
        assert active and command.action_id == proposal.action_id
        events.append("permanent-dispatch")

    async def enqueue(session: AsyncSession, command: SegmentCommand, registration: object) -> None:
        assert active and registration == REGISTRATION
        events.append("enqueue")
        if late_enqueue:
            operation.end = clock_us() - 1

    async def clock(session: AsyncSession) -> datetime:
        if late_enqueue and "enqueue" in events:
            raise AssertionError("late enqueue cannot start another DB read")
        return now

    monkeypatch.setattr(module, "runtime_transaction", transaction)
    monkeypatch.setattr(module, "_fresh", fresh)
    monkeypatch.setattr(module, "authorize_registered_pending_locked", authorize)
    monkeypatch.setattr(module, "reserve_dispatch", reserve)
    monkeypatch.setattr(module, "_enqueue_exact", enqueue)
    monkeypatch.setattr(module, "db_now", clock)
    monkeypatch.setattr(
        operation.prepared, "validate_loaded_locked", AsyncMock(return_value=operation.end)
    )
    monkeypatch.setattr(
        module,
        "state_locked",
        AsyncMock(
            return_value=CodingState(
                snapshot(work),
                prepared.binding.goal,
                prepared.binding.plan.plan_id,
                prepared.binding.plan,
                "p1",
                now,
                clock_us(),
            )
        ),
    )
    monkeypatch.setattr(value.contexts, "revalidate_context", AsyncMock(return_value=()))
    monkeypatch.setattr(module, "require_effect_authority", AsyncMock())
    monkeypatch.setattr(module, "require_current_work_caps", AsyncMock())
    monkeypatch.setattr(module, "route_prepared", lambda *args: SimpleNamespace(quote=quote))
    if late_enqueue:
        with pytest.raises(TimeoutError):
            await module._authorize(operation, loaded, original.proposal_hash)
        assert events == [
            "control-first",
            "fresh",
            "authorize-hold",
            "permanent-dispatch",
            "enqueue",
            "rollback",
        ]
    else:
        result = await module._authorize(operation, loaded, original.proposal_hash)
        assert result.disposition == "enqueued" and result.command.action_id == proposal.action_id
        assert events == [
            "control-first",
            "fresh",
            "authorize-hold",
            "permanent-dispatch",
            "enqueue",
            "commit",
        ]
    operation.finish()
