"""Actual current mixed-cycle reservations; never a permit, registration or budget refill."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.cycle_admission import (
    validate_stockflow_cycle,
    validate_stockflow_cycle_configuration,
)
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementPlanTask,
    ManagementProcedure,
    ManagementRevisionEvent,
)
from nexus.company.management.plan_registration import registration, require_native_task
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import RunBinding
from nexus.company.management.revision_store import (
    plan_record,
    plan_reference,
    require_current_governance,
)
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.cycle_partition_support import _execution, _require, _root, _same
from nexus.execution.runtime_contracts import (
    AttemptQuota,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import (
    KINDS,
    require_runtime_scope,
    snapshot,
)
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl


async def _current_plan(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    admission: StockFlowCycleAdmission,
    registry: ModelRegistry,
) -> tuple[PlanRevision, ManagementOwnerDecision]:
    # This >50-line read keeps the exact current binding, owner decision and governance adjacent.
    binding = await ManagementPlanStore.current_binding(session, work.company_id, work.task_id)
    _require(binding is not None)
    assert binding is not None
    row = await session.get(
        ManagementPlanRevision, (work.company_id, binding.plan.plan_revision_id)
    )
    _require(row is not None)
    assert row is not None
    record = plan_record(row)
    selected = validate_stockflow_cycle(admission, registry, record.payload)
    _require(
        selected is not None and selected.stage == "full" and binding.plan == plan_reference(record)
    )
    assert selected is not None
    _require(work.task_id in (*selected.native_task_ids, selected.sender_task_id))
    head = await session.get(ManagementPlanHead, (work.company_id, record.plan_id))
    _require(head is not None)
    assert head is not None
    decision = await session.get(ManagementOwnerDecision, (work.company_id, head.decision_id))
    _require(decision is not None)
    assert decision is not None
    _require(
        _same(
            head,
            "state current_revision_id goal_id procedure_id",
            (
                "approved",
                record.plan_revision_id,
                admission.goal.goal_id,
                admission.procedure.procedure_id,
            ),
        )
    )
    _require(
        _same(
            decision,
            "kind owner_id plan_revision_id payload_sha256",
            ("approve", control.owner_id, record.plan_revision_id, record.sha256),
        )
    )
    _require(identity.principal_id == work.actor_id and identity.workspace_id == work.workspace_id)
    await require_current_governance(session, control, binding.plan, binding.child)
    return record, decision


async def _procedure(
    session: AsyncSession,
    admission: StockFlowCycleAdmission,
) -> ManagementProcedure:
    row = await session.scalar(
        select(ManagementProcedure).where(
            ManagementProcedure.company_id == admission.company_id,
            ManagementProcedure.goal_id == admission.goal.goal_id,
        )
    )
    _require(row is not None)
    assert row is not None
    root = admission.procedure
    _require(
        (
            row.procedure_id,
            row.parent_task_id,
            row.parent_run_id,
            row.allocation_usd,
            RunBinding.model_validate_json(row.binding_json),
            AttemptQuota.model_validate_json(row.quota_json),
        )
        == (
            root.procedure_id,
            root.binding.task_id,
            root.binding.run_id,
            root.allocation_usd,
            root.binding,
            root.quota,
        )
    )
    _require(
        await ManagementPlanStore.managed_kind(session, admission.company_id, root.binding.task_id)
        == "procedure"
    )
    return row


async def _family(
    session: AsyncSession,
    admission: StockFlowCycleAdmission,
) -> tuple[dict[UUID, RegisteredWork], dict[UUID, ExecutionWork]]:
    root = admission.procedure.binding.task_id
    expected = {root, *(row.child.binding.task_id for row in admission.slots)}
    directories = list(
        (
            await session.scalars(
                select(RegisteredWork)
                .where(
                    RegisteredWork.company_id == admission.company_id,
                    RegisteredWork.root_task_id == root,
                )
                .order_by(RegisteredWork.task_id)
                .limit(1001)
                .with_for_update()
            )
        ).all()
    )
    _require(len(directories) <= 1000 and len(directories) == len(expected))
    _require({row.task_id for row in directories} == expected)
    executions = list(
        (
            await session.scalars(
                select(ExecutionWork)
                .where(
                    ExecutionWork.company_id == admission.company_id,
                    or_(
                        ExecutionWork.task_id.in_(expected),
                        ExecutionWork.parent_task_id.in_(expected),
                    ),
                )
                .order_by(ExecutionWork.task_id)
                .limit(1001)
                .with_for_update()
            )
        ).all()
    )
    _require(len(executions) <= 1000 and len(executions) == len(expected))
    _require({row.task_id for row in executions} == expected)
    return {row.task_id: row for row in directories}, {row.task_id: row for row in executions}


async def _children(
    session: AsyncSession,
    admission: StockFlowCycleAdmission,
    record: PlanRevision,
    directories: dict[UUID, RegisteredWork],
    executions: dict[UUID, ExecutionWork],
) -> None:
    # This >50-line loop retains each exact current sibling and its permanent registration slice.
    for slot in admission.slots:
        child, expected = slot.child, slot.child.binding
        directory, work = directories[expected.task_id], executions[expected.task_id]
        binding = await ManagementPlanStore.current_binding(
            session, admission.company_id, expected.task_id
        )
        _require(binding is not None)
        assert binding is not None
        _require(
            binding.plan == plan_reference(record)
            and binding.child == child
            and binding.work == slot.work
            and binding.procedure_id == admission.procedure.procedure_id
        )
        native = await session.get(
            ManagementPlanTask, (admission.company_id, record.plan_revision_id, expected.task_id)
        )
        _require(native is not None)
        assert native is not None
        require_native_task(native, work, child, record.payload)
        _execution(work, registration(expected, slot.work, child.quota))
        _require(
            _same(
                directory,
                "company_id workspace_id actor_id trace_id parent_task_id "
                "root_task_id allocation_usd delegated_usd",
                (
                    admission.company_id,
                    expected.workspace_id,
                    expected.actor_id,
                    expected.trace_id,
                    admission.procedure.binding.task_id,
                    admission.procedure.binding.task_id,
                    child.allocation_usd,
                    Decimal(0),
                ),
            )
        )
        _require(
            work.parent_task_id == admission.procedure.binding.task_id
            and work.workspace_id == expected.workspace_id
            and work.actor_id == expected.actor_id
        )
        _require(all(getattr(work, f"{kind}_delegated") == 0 for kind in KINDS))


async def _revision(
    session: AsyncSession,
    control: CompanyControl,
    admission: StockFlowCycleAdmission,
    registry: ModelRegistry,
    record: PlanRevision,
    decision: ManagementOwnerDecision,
) -> None:
    # This >50-line check retains the original/current plan and exact owner revision evidence.
    root = admission.procedure
    events = list(
        (
            await session.scalars(
                select(ManagementRevisionEvent)
                .where(
                    ManagementRevisionEvent.company_id == admission.company_id,
                    ManagementRevisionEvent.procedure_id == root.procedure_id,
                )
                .limit(3)
            )
        ).all()
    )
    _require(len(events) == 1)
    event = events[0]
    _require(
        _same(
            event,
            "company_id procedure_id parent_task_id parent_run_id next_plan_revision_id "
            "owner_decision_id owner_id revision_counter",
            (
                admission.company_id,
                root.procedure_id,
                root.binding.task_id,
                root.binding.run_id,
                record.plan_revision_id,
                decision.decision_id,
                control.owner_id,
                1,
            ),
        )
    )
    previous = await session.get(
        ManagementPlanRevision, (admission.company_id, event.previous_plan_revision_id)
    )
    _require(previous is not None)
    assert previous is not None
    original = plan_record(previous)
    selected = validate_stockflow_cycle(admission, registry, original.payload)
    _require(
        selected is not None
        and selected.stage == "strategy"
        and original.plan_revision_id != record.plan_revision_id
    )
    earlier = list(
        (
            await session.scalars(
                select(ManagementOwnerDecision)
                .where(
                    ManagementOwnerDecision.company_id == admission.company_id,
                    ManagementOwnerDecision.plan_revision_id == original.plan_revision_id,
                    ManagementOwnerDecision.kind == "approve",
                )
                .limit(2)
            )
        ).all()
    )
    _require(len(earlier) == 1)
    old = earlier[0]
    _require(
        _same(
            old,
            "company_id owner_id kind plan_revision_id payload_sha256",
            (
                admission.company_id,
                control.owner_id,
                "approve",
                original.plan_revision_id,
                original.sha256,
            ),
        )
    )
    _require(old.recorded_at <= decision.recorded_at == event.recorded_at)


async def require_cycle_native_partition(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    *,
    admission: StockFlowCycleAdmission,
    registry: ModelRegistry,
) -> None:
    """Qualify actual reservations only, inside the caller's existing company-first transaction."""
    # This >50-line orchestration keeps every read and final partition comparison in one session.
    _require(session.in_transaction() and isinstance(admission, StockFlowCycleAdmission))
    checked = validate_stockflow_cycle_configuration(admission, registry)
    _require(control.company_id == work.company_id == checked.company_id)
    actual_control = await session.scalar(
        select(CompanyControl)
        .where(CompanyControl.company_id == checked.company_id)
        .with_for_update()
    )
    _require(actual_control is control and not control.paused)
    actual = await session.scalar(
        select(ExecutionWork)
        .where(
            ExecutionWork.company_id == checked.company_id, ExecutionWork.task_id == work.task_id
        )
        .with_for_update()
    )
    _require(
        actual is work
        and identity.principal_id == work.actor_id
        and identity.workspace_id == work.workspace_id
    )
    registered = await require_runtime_scope(
        session,
        control,
        LedgerScope(
            company_id=work.company_id,
            task_id=work.task_id,
            trace_id=work.trace_id,
            principal_id=identity.principal_id,
        ),
        identity,
        allow_inactive=False,
        owner_read=False,
    )
    _require(checked.slots[-1].child.binding.actor_id == control.owner_id)
    record, decision = await _current_plan(session, control, work, identity, checked, registry)
    await _procedure(session, checked)
    directories, executions = await _family(session, checked)
    _require(registered is directories[work.task_id] and executions[work.task_id] is work)
    root = checked.procedure.binding.task_id
    parent, allocated = executions[root], directories[root]
    _root(checked, allocated, parent)
    await _children(session, checked, record, directories, executions)
    _require(allocated.delegated_usd == sum(row.child.allocation_usd for row in checked.slots))
    for kind in KINDS:
        _require(
            getattr(parent, f"{kind}_delegated")
            == sum(
                getattr(snapshot(executions[row.child.binding.task_id]).registration.quota, kind)
                for row in checked.slots
            )
        )
    _require(
        _same(work, "model_requests_limit model_requests_used model_requests_delegated", (0, 0, 0))
    )
    await _revision(session, control, checked, registry, record, decision)
