"""Transaction orchestration only; mocked proof boundaries do not qualify native proof or SQL."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_transition_store import approve_transition_locked
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.cycle_full_structural_support import configured
from nexus.tests.unit.test_plan_choice_wire_integration import selection


@pytest.mark.parametrize("replay", [False, True])
async def test_approval_and_replay_recheck_after_staged_head_then_finish_last(replay: bool) -> None:
    data = configured()
    payload = declared(data.admission, 2).model_copy(update={"strategy_selection": selection()})
    now = datetime(2026, 10, 15, tzinfo=UTC)
    revision = UUID(int=901)
    old = UUID(int=900)
    record = PlanRevision(
        company_id=payload.company_id,
        plan_id=payload.plan.plan_id,
        plan_revision_id=revision,
        revision=2,
        sha256=canonical_sha256(payload),
        payload=payload,
        proposed_by=payload.procedure.binding.actor_id,
        recorded_at=now,
    )
    head = ManagementPlanHead(
        company_id=payload.company_id,
        plan_id=payload.plan.plan_id,
        current_revision_id=revision if replay else old,
        goal_id=payload.goal.goal_id,
        procedure_id=payload.procedure.procedure_id,
        decision_id=UUID(int=902),
        state="approved",
    )
    calls: list[str] = []
    scope = CompanyControlScope(
        company_id=payload.company_id,
        principal_id=payload.procedure.binding.actor_id,
        operation_id=UUID(int=903),
        trace_id=UUID(int=904),
    )
    identity = VerifiedIdentity(
        principal_id=scope.principal_id, workspace_id=payload.procedure.binding.workspace_id
    )
    first = SimpleNamespace(admission=SimpleNamespace(charters={}))
    current = SimpleNamespace(admission=SimpleNamespace(charters={}))
    session = MagicMock(spec=AsyncSession)

    async def flush() -> None:
        calls.append("flush")
        assert head.current_revision_id == revision

    async def proof(*args: object, **kwargs: object) -> object:
        calls.append("proof")
        if calls.count("proof") == 1:
            return first
        assert head.current_revision_id == revision
        return current

    async def partition(*args: object) -> None:
        calls.append("partition")

    async def finish(*args: object) -> None:
        calls.append("finish")
        assert args[-2:] == (first, current)

    session.flush = AsyncMock(side_effect=flush)
    module = "nexus.company.management.plan_transition_store."
    with (
        patch(module + "_transition_inputs", return_value=(object(), object(), object())),
        patch(module + "read_strategy_transition_locked", AsyncMock(side_effect=proof)),
        patch(module + "require_transition_partition_locked", AsyncMock(side_effect=partition)),
        patch(module + "finish_transition_locked", AsyncMock(side_effect=finish)),
        patch(module + "db_clock", AsyncMock(return_value=now)),
        patch(
            module + "ensure_procedure",
            AsyncMock(return_value=SimpleNamespace(procedure_id=payload.procedure.procedure_id)),
        ) as ensure,
        patch(
            module + "decision_locked",
            AsyncMock(return_value=SimpleNamespace(decision_id=UUID(int=905))),
        ) as decision,
        patch(module + "consume_revision", AsyncMock()) as consume,
        patch(module + "register_children", AsyncMock()) as register,
    ):
        value = await approve_transition_locked(
            cast(ManagementPlanStore, SimpleNamespace(catalog=data.catalog, directory=object())),
            session,
            cast(CompanyControl, object()),
            scope,
            identity,
            record,
            head,
            old,
            None,
        )
    assert value == record
    assert calls == (
        ["proof", "partition", "proof", "partition", "finish"]
        if replay
        else ["proof", "partition", "flush", "proof", "partition", "finish"]
    )
    for write in (ensure, decision, consume, register):
        assert write.await_count == (0 if replay else 1)


async def test_approved_replay_does_not_return_before_current_proof_denial() -> None:
    # A failing actual boundary must propagate; this narrow test does not manufacture a proof.
    module = "nexus.company.management.plan_transition_store."
    with (
        patch(module + "_transition_inputs", return_value=(object(), object(), object())),
        patch(
            module + "read_strategy_transition_locked",
            AsyncMock(side_effect=ManagementDeniedError("expired")),
        ),
        pytest.raises(ManagementDeniedError, match="expired"),
    ):
        await approve_transition_locked(
            cast(ManagementPlanStore, SimpleNamespace(catalog=object())),
            cast(AsyncSession, object()),
            cast(CompanyControl, object()),
            cast(CompanyControlScope, object()),
            cast(VerifiedIdentity, object()),
            cast(PlanRevision, SimpleNamespace(payload=object())),
            cast(ManagementPlanHead, SimpleNamespace(state="approved")),
            None,
            None,
        )
