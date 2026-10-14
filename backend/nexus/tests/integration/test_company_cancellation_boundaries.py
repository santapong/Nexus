"""Actual cancellation fences fresh capacity/dispatch while preserving issued reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.results import ActionReceipt
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.company.management.cancellation_support import WorkCancelledError
from nexus.company.management.plan_models import ManagementOwnerDecision
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.dispatch_store import reserve_dispatch
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_store import ExecutionStore, next_segment_id
from nexus.execution.runtime_support import runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold, DailyBudget, WorkBudget
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_cancellation import _approved
from nexus.tests.management_cancellation_support import cancellation_factory as cancellation_factory
from nexus.tests.management_plan_support import authorized_action, configured_plan
from nexus.tests.management_plan_support import binding as new_binding


def _scope(bound: RunBinding) -> LedgerScope:
    return LedgerScope(
        company_id=bound.company_id,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )


async def _cancel(factory: async_sessionmaker[AsyncSession], bound: RunBinding) -> None:
    await WorkCancellationStore(factory).cancel(
        control().model_copy(update={"operation_id": uuid4()}),
        identity(OWNER),
        CancellationCommand(company_id=COMPANY, target=bound, reason="Permanent native stop"),
    )


async def _reserve(
    factory: async_sessionmaker[AsyncSession], bound: RunBinding, command: SegmentCommand
) -> None:
    async with runtime_transaction(factory, _scope(bound), identity(bound.actor_id)) as (
        session,
        _,
        _,
    ):
        await reserve_dispatch(
            session,
            command,
            workflow_name=bound.workflow_name,
            workflow_version=bound.workflow_version,
        )


async def test_cancel_denies_fresh_dispatch_and_recovery_but_keeps_exact_dispatch_history(
    cancellation_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    plans, payload, _ = await _approved(cancellation_factory, tmp_path)
    bound = payload.children[0].binding
    execution = ExecutionStore(cancellation_factory, management_catalog=plans.catalog)
    action = await authorized_action(cancellation_factory, bound)
    command = SegmentCommand(
        **bound.model_dump(
            include={"company_id", "task_id", "trace_id", "actor_id", "workspace_id", "run_id"}
        ),
        action_id=action.action_id,
        segment_id=next_segment_id(await execution.get(_scope(bound), identity(bound.actor_id))),
    )
    await _reserve(cancellation_factory, bound, command)
    await _cancel(cancellation_factory, payload.procedure.binding)
    await _reserve(cancellation_factory, bound, command)
    sibling = payload.children[1].binding
    second = await authorized_action(cancellation_factory, sibling)
    fresh = SegmentCommand(
        **sibling.model_dump(
            include={"company_id", "task_id", "trace_id", "actor_id", "workspace_id", "run_id"}
        ),
        action_id=second.action_id,
        segment_id=next_segment_id(
            await execution.get(_scope(sibling), identity(sibling.actor_id))
        ),
    )
    with pytest.raises(WorkCancelledError):
        await _reserve(cancellation_factory, sibling, fresh)
    with pytest.raises(WorkCancelledError):
        await execution.recover_dispatched(
            _scope(bound), identity(bound.actor_id), uuid4(), command.segment_id
        )
    async with cancellation_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 1
    assert (await execution.get(_scope(bound), identity(bound.actor_id))).segment_number == 0


async def test_existing_execute_lease_cannot_renew_or_spend_another_attempt_after_cancel(
    cancellation_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    plans, payload, _ = await _approved(cancellation_factory, tmp_path)
    bound = payload.children[0].binding
    execution = ExecutionStore(cancellation_factory, management_catalog=plans.catalog)
    lease = await execution.claim(_scope(bound), identity(bound.actor_id), uuid4())
    before = await execution.get(_scope(bound), identity(bound.actor_id))
    await _cancel(cancellation_factory, bound)
    with pytest.raises(WorkCancelledError):
        await execution.reserve_attempt(lease, identity(bound.actor_id), "model_requests", uuid4())
    with pytest.raises(WorkCancelledError):
        await execution.renew(lease, identity(bound.actor_id))
    assert await execution.get(_scope(bound), identity(bound.actor_id)) == before


async def test_owner_approval_rechecks_stop_after_a_valid_prepared_proposal(
    cancellation_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    plans, payload, _ = await _approved(cancellation_factory, tmp_path)
    pending = await plans.propose(
        control(),
        identity(OWNER),
        payload.model_copy(update={"plan": payload.plan.model_copy(update={"plan_id": uuid4()})}),
        expected_current_revision_id=None,
    )
    execution = ExecutionStore(cancellation_factory, management_catalog=plans.catalog)
    parent = payload.procedure.binding
    before = await execution.get(_scope(parent), identity(OWNER))
    await _cancel(cancellation_factory, parent)
    with pytest.raises(WorkCancelledError):
        await plans.approve_and_register(
            control(),
            identity(OWNER),
            pending.plan_revision_id,
            pending.sha256,
            expected_current_revision_id=pending.plan_revision_id,
        )
    assert await execution.get(_scope(parent), identity(OWNER)) == before
    async with cancellation_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(ManagementOwnerDecision)) == 1
        assert await session.scalar(select(func.count()).select_from(RegisteredWork)) == 3


async def test_cancelled_goal_procedure_cannot_be_replaced_with_new_root_or_run_identifiers(
    cancellation_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Complete alternate DAG pins stay in this >50-line case to prove all new IDs
    # still bind the same cancelled native goal, rather than an invalid payload.
    plans, payload, _ = await _approved(cancellation_factory, tmp_path)
    await _cancel(cancellation_factory, payload.procedure.binding)
    replacements = {
        child.binding.task_id: new_binding(child.binding.actor_id) for child in payload.children
    }
    attempted = payload.model_copy(
        update={
            "plan": payload.plan.model_copy(
                update={
                    "plan_id": uuid4(),
                    "items": tuple(
                        row.model_copy(
                            update={
                                "task_id": replacements[row.task_id].task_id,
                                "trace_id": replacements[row.task_id].trace_id,
                                "depends_on": tuple(
                                    replacements[key].task_id for key in row.depends_on
                                ),
                            }
                        )
                        for row in payload.plan.items
                    ),
                }
            ),
            "procedure": payload.procedure.model_copy(
                update={"procedure_id": uuid4(), "binding": new_binding(OWNER)}
            ),
            "children": tuple(
                child.model_copy(update={"binding": replacements[child.binding.task_id]})
                for child in payload.children
            ),
            "verification": tuple(
                edge.model_copy(
                    update={
                        "author_task_id": replacements[edge.author_task_id].task_id,
                        "verifier_task_id": replacements[edge.verifier_task_id].task_id,
                    }
                )
                for edge in payload.verification
            ),
        }
    )
    attempted = PlanPayload.model_validate_json(attempted.model_dump_json())
    with pytest.raises(WorkCancelledError):
        await plans.propose(
            control(), identity(OWNER), attempted, expected_current_revision_id=None
        )


async def test_exact_child_stop_leaves_unrelated_sibling_eligible_under_current_plan(
    cancellation_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    plans, payload = await configured_plan(cancellation_factory, tmp_path)
    extra = payload.children[0].model_copy(
        update={"binding": new_binding(payload.children[0].binding.actor_id)}
    )
    item = payload.plan.items[0].model_copy(
        update={"task_id": extra.binding.task_id, "trace_id": extra.binding.trace_id}
    )
    payload = payload.model_copy(
        update={
            "children": (*payload.children, extra),
            "plan": payload.plan.model_copy(update={"items": (*payload.plan.items, item)}),
        }
    )
    proposed = await plans.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    await _cancel(cancellation_factory, payload.children[0].binding)
    execution = ExecutionStore(cancellation_factory, management_catalog=plans.catalog)
    lease = await execution.claim(_scope(extra.binding), identity(extra.binding.actor_id), uuid4())
    assert lease.task_id == extra.binding.task_id and lease.mode == "execute"


async def _ledger_facts(
    factory: async_sessionmaker[AsyncSession], action_id: UUID
) -> tuple[tuple[object, ...], ...]:
    """Exact native accounting/allocation observations, not inferred counter refunds."""
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        allocation = (
            await session.execute(
                select(
                    RegisteredWork.task_id,
                    RegisteredWork.allocation_usd,
                    RegisteredWork.delegated_usd,
                ).order_by(RegisteredWork.task_id)
            )
        ).all()
        work = (
            await session.execute(
                select(WorkBudget.task_id, WorkBudget.held_usd, WorkBudget.spent_usd).order_by(
                    WorkBudget.task_id
                )
            )
        ).all()
        daily = (
            await session.execute(
                select(DailyBudget.day, DailyBudget.held_usd, DailyBudget.spent_usd)
            )
        ).all()
        hold = await session.get(CostHold, action_id)
        assert hold is not None
        return (
            *(tuple(row) for row in allocation),
            *(tuple(row) for row in work),
            *(tuple(row) for row in daily),
            (hold.action_id, hold.amount_usd, hold.actual_usd, hold.state),
        )


async def test_cancelled_issued_intent_reconciles_without_refunds_new_effects_or_parent_reset(
    cancellation_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Keep actual issue/cancel/reconcile/accounting observations together; these
    # >50 lines prove history preservation without injecting a receipt or counter.
    plans, payload, _ = await _approved(cancellation_factory, tmp_path)
    bound = payload.children[0].binding
    execution = ExecutionStore(cancellation_factory, management_catalog=plans.catalog)
    effects = EffectStore(cancellation_factory, management_catalog=plans.catalog)
    action = await authorized_action(cancellation_factory, bound)
    original = await execution.claim(_scope(bound), identity(bound.actor_id), uuid4())
    await effects.begin(original, identity(bound.actor_id), action.action_id)
    before = await _ledger_facts(cancellation_factory, action.action_id)
    await _cancel(cancellation_factory, payload.procedure.binding)
    assert await _ledger_facts(cancellation_factory, action.action_id) == before
    await execution.release(original, identity(bound.actor_id))
    current = await execution.claim(
        _scope(bound), identity(bound.actor_id), uuid4(), reconcile_only=True
    )
    assert current.mode == "reconcile"
    assert (
        await effects.get(current, identity(bound.actor_id), action.action_id)
    ).state == "outcome_unknown"
    assert (
        await execution.get(_scope(bound), identity(bound.actor_id))
    ).counters.tool_attempts == 1
    receipt = ActionReceipt(
        company_id=COMPANY,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
    )
    assert (
        await effects.reconcile(current, identity(bound.actor_id), receipt, actual_usd=None)
    ).state == "succeeded"
    unknown = await _ledger_facts(cancellation_factory, action.action_id)
    assert unknown[:-1] == before[:-1] and unknown[-1][-1] == "unknown"
    assert unknown[-1][1:3] == (Decimal("0.03"), None)
    second = await authorized_action(cancellation_factory, bound)
    with pytest.raises(ValueError):
        await effects.begin(current, identity(bound.actor_id), second.action_id)
    assert (
        await execution.get(_scope(bound), identity(bound.actor_id))
    ).counters.tool_attempts == 1


async def test_cancellation_retains_positive_spent_cost_outstanding_hold_and_parent_partition(
    cancellation_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    plans, payload, _ = await _approved(cancellation_factory, tmp_path)
    bound = payload.children[0].binding
    execution = ExecutionStore(cancellation_factory, management_catalog=plans.catalog)
    effects = EffectStore(cancellation_factory, management_catalog=plans.catalog)
    completed = await authorized_action(cancellation_factory, bound)
    lease = await execution.claim(_scope(bound), identity(bound.actor_id), uuid4())
    await effects.begin(lease, identity(bound.actor_id), completed.action_id)
    receipt = ActionReceipt(
        company_id=COMPANY,
        receipt_id=uuid4(),
        action_id=completed.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_hash=action_hash(completed),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
    )
    await effects.record_receipt(
        lease, identity(bound.actor_id), receipt, actual_usd=Decimal("0.02")
    )
    held = await authorized_action(cancellation_factory, bound)
    before = await _ledger_facts(cancellation_factory, completed.action_id)
    outstanding = await _ledger_facts(cancellation_factory, held.action_id)
    assert before[-1][1:] == (Decimal("0.03"), Decimal("0.02"), "reconciled")
    assert outstanding[-1][1:] == (Decimal("0.03"), None, "held")
    await _cancel(cancellation_factory, payload.procedure.binding)
    assert await _ledger_facts(cancellation_factory, completed.action_id) == before
    assert await _ledger_facts(cancellation_factory, held.action_id) == outstanding
    known = await effects.get(lease, identity(bound.actor_id), completed.action_id)
    assert known.receipt == receipt and known.state == "succeeded"
    with pytest.raises(WorkCancelledError):
        await effects.begin(lease, identity(bound.actor_id), held.action_id)
    assert (
        await execution.get(_scope(bound), identity(bound.actor_id))
    ).counters.tool_attempts == 1
