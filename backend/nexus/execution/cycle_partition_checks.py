"""Actual current mixed-cycle reservations; never a permit, registration or budget refill."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
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
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.revision_store import (
    plan_record,
    plan_reference,
    require_current_governance,
)
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.cycle_family_facts import _children, _family, _procedure, _revision
from nexus.execution.cycle_partition_support import _require, _root, _same
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
    _require(work.task_id in {slot.child.binding.task_id for slot in admission.slots})
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


async def read_current_cycle_family_locked(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    *,
    admission: StockFlowCycleAdmission,
    registry: ModelRegistry,
) -> PlanRevision:
    """Read one exact configured child and its complete current locked family."""
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
    await _revision(session, control, checked, registry, record, decision)
    return record


async def require_cycle_native_partition(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    *,
    admission: StockFlowCycleAdmission,
    registry: ModelRegistry,
) -> None:
    """Retain E/EV/sender membership and zero model allowance at the native boundary."""
    record = await read_current_cycle_family_locked(
        session, control, work, identity, admission=admission, registry=registry
    )
    selected = validate_stockflow_cycle(admission, registry, record.payload)
    _require(selected is not None)
    assert selected is not None
    _require(work.task_id in (*selected.native_task_ids, selected.sender_task_id))
    _require(
        _same(work, "model_requests_limit model_requests_used model_requests_delegated", (0, 0, 0))
    )
