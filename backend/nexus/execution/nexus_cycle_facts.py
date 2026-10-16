"""Locked current Nexus family facts; no lease, registration, permit or quota replenishment."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.results import ActionReceipt
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.nexus_coding_catalog import NexusAdmission
from nexus.company.management.nexus_cycle_admission import NexusStage
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanRevision,
    ManagementPlanTask,
    ManagementProcedure,
    ManagementRevisionEvent,
)
from nexus.company.management.plan_registration import registration, require_native_task
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import _actor
from nexus.company.management.plans import RunBinding
from nexus.company.management.revision_store import (
    plan_record,
    plan_reference,
    require_current_governance,
)
from nexus.execution.runtime_contracts import (
    AttemptQuota,
    ExecutionDeniedError,
    ExecutionRegistration,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import KINDS, snapshot
from nexus.harness.journal_models import CompanyControl, CostHold


def _require(value: bool) -> None:
    if not value:
        raise ExecutionDeniedError("Current Nexus permanent family is unavailable")


def _fields(row: object, names: str) -> tuple[object, ...]:
    return tuple(getattr(row, name) for name in names.split())


def _execution(row: ExecutionWork, expected: ExecutionRegistration) -> None:
    _require(snapshot(row).registration == expected)
    for kind in KINDS:
        limit, used, delegated = _fields(row, f"{kind}_limit {kind}_used {kind}_delegated")
        _require(type(limit) is type(used) is type(delegated) is int)
        assert isinstance(limit, int) and isinstance(used, int) and isinstance(delegated, int)
        _require(
            limit == getattr(expected.quota, kind)
            and min(used, delegated) >= 0
            and used + delegated <= limit
        )


async def _rows(
    session: AsyncSession, admission: NexusAdmission, stage: NexusStage
) -> tuple[dict[UUID, RegisteredWork], dict[UUID, ExecutionWork]]:
    root = admission.procedure.binding.task_id
    slots = admission.slots[:1] if stage == "planning" else admission.slots
    expected = {root, *(slot.work.task_id for slot in slots)}
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
    _require(
        len(directories) == len(executions) == len(expected)
        and {row.task_id for row in directories} == {row.task_id for row in executions} == expected
    )
    return {row.task_id: row for row in directories}, {row.task_id: row for row in executions}


async def _family(
    session: AsyncSession,
    control: CompanyControl,
    admission: NexusAdmission,
    record: PlanRevision,
    stage: NexusStage,
) -> tuple[dict[UUID, RegisteredWork], dict[UUID, ExecutionWork]]:
    slots = admission.slots[:1] if stage == "planning" else admission.slots
    root = admission.procedure
    bound = root.binding
    procedure = await session.scalar(
        select(ManagementProcedure).where(
            ManagementProcedure.company_id == control.company_id,
            ManagementProcedure.goal_id == admission.goal.goal_id,
        )
    )
    _require(procedure is not None)
    assert procedure is not None
    _require(
        _fields(procedure, "procedure_id parent_task_id parent_run_id allocation_usd")
        == (root.procedure_id, bound.task_id, bound.run_id, root.allocation_usd)
        and RunBinding.model_validate_json(procedure.binding_json) == bound
        and AttemptQuota.model_validate_json(procedure.quota_json) == root.quota
    )
    directories, executions = await _rows(session, admission, stage)
    directory, parent = directories[bound.task_id], executions[bound.task_id]
    item = WorkItem(
        company_id=control.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        goal_id=root.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        acceptance=("management.non-executing-allocation.v1",),
        budget_usd=root.allocation_usd,
    )
    _execution(parent, registration(bound, item, root.quota))
    _require(
        _fields(
            directory,
            "company_id workspace_id actor_id trace_id parent_task_id root_task_id "
            "allocation_usd active",
        )
        == (
            control.company_id,
            bound.workspace_id,
            bound.actor_id,
            bound.trace_id,
            None,
            bound.task_id,
            root.allocation_usd,
            True,
        )
    )
    _require(
        _fields(
            parent,
            "parent_task_id state fence segment_number worker_id "
            "lease_until segment_id waiting_action_id lease_mode lease_principal_id",
        )
        == (None, "eligible", 0, 0, None, None, None, None, None, None)
    )
    _require(
        _fields(
            parent, "model_requests_used tool_attempts_used rework_rounds_used plan_revisions_used"
        )
        == (0, 0, 0, int(stage == "execution"))
    )
    _require(directory.delegated_usd == sum(slot.child.allocation_usd for slot in slots))
    for kind in KINDS:
        _require(
            getattr(parent, f"{kind}_delegated")
            == sum(getattr(slot.child.quota, kind) for slot in slots)
        )
    items = {item.task_id: item for item in record.payload.plan.items}
    for slot in slots:
        child = slot.child
        binding = child.binding
        directory, work = directories[binding.task_id], executions[binding.task_id]
        _execution(work, registration(binding, items[work.task_id], child.quota))
        _require(
            work.parent_task_id == bound.task_id
            and all(getattr(work, f"{kind}_delegated") == 0 for kind in KINDS)
        )
        _require(
            _fields(
                directory,
                "company_id workspace_id actor_id trace_id parent_task_id root_task_id "
                "allocation_usd delegated_usd active",
            )
            == (
                control.company_id,
                binding.workspace_id,
                binding.actor_id,
                binding.trace_id,
                bound.task_id,
                bound.task_id,
                child.allocation_usd,
                0,
                True,
            )
        )
        current = await ManagementPlanStore.current_binding(
            session, control.company_id, work.task_id
        )
        _require(current is not None)
        assert current is not None
        _require(
            current.plan == plan_reference(record)
            and current.child == child
            and current.work == items[work.task_id]
            and current.procedure_id == root.procedure_id
        )
        task = await session.get(
            ManagementPlanTask, (control.company_id, record.plan_revision_id, work.task_id)
        )
        _require(task is not None)
        assert task is not None
        require_native_task(task, work, child, record.payload)
        await _actor(session, control, binding.actor_id)
        await require_current_governance(session, control, current.plan, current.child)
    return directories, executions


async def _transition(
    session: AsyncSession,
    control: CompanyControl,
    admission: NexusAdmission,
    record: PlanRevision,
    decision: ManagementOwnerDecision,
    stage: NexusStage,
    executions: dict[UUID, ExecutionWork],
) -> None:
    root = admission.procedure
    events = list(
        (
            await session.scalars(
                select(ManagementRevisionEvent)
                .where(
                    ManagementRevisionEvent.company_id == control.company_id,
                    ManagementRevisionEvent.procedure_id == root.procedure_id,
                )
                .limit(3)
            )
        ).all()
    )
    if stage == "planning":
        _require(not events)
        return
    _require(len(events) == 1)
    event = events[0]
    _require(
        _fields(
            event,
            "company_id procedure_id parent_task_id parent_run_id next_plan_revision_id "
            "owner_decision_id owner_id revision_counter",
        )
        == (
            control.company_id,
            root.procedure_id,
            root.binding.task_id,
            root.binding.run_id,
            record.plan_revision_id,
            decision.decision_id,
            control.owner_id,
            1,
        )
    )
    previous = await session.get(
        ManagementPlanRevision, (control.company_id, event.previous_plan_revision_id)
    )
    _require(previous is not None)
    assert previous is not None
    original = plan_record(previous)
    _require(
        original.payload == admission.payload("planning")
        and original.plan_id == record.plan_id
        and original.plan_revision_id != record.plan_revision_id
    )
    earlier = list(
        (
            await session.scalars(
                select(ManagementOwnerDecision)
                .where(
                    ManagementOwnerDecision.company_id == control.company_id,
                    ManagementOwnerDecision.plan_revision_id == original.plan_revision_id,
                    ManagementOwnerDecision.kind == "approve",
                )
                .limit(2)
            )
        ).all()
    )
    _require(
        len(earlier) == 1
        and _fields(earlier[0], "owner_id plan_revision_id payload_sha256 kind")
        == (control.owner_id, original.plan_revision_id, original.sha256, "approve")
    )
    origin = record.payload.planning_origin
    _require(origin is not None)
    assert origin is not None
    planner = executions[admission.slots[0].work.task_id]
    intent = await session.get(EffectIntent, (control.company_id, origin.action_id))
    held = await session.get(CostHold, origin.action_id)
    _require(intent is not None and held is not None)
    assert intent is not None and held is not None
    receipt = ActionReceipt.model_validate_json(intent.receipt_json or "")
    _require(
        (origin.source_plan_id, origin.source_plan_revision_id, origin.task_id)
        == (original.plan_id, original.plan_revision_id, planner.task_id)
    )
    _require(
        _fields(planner, "state worker_id lease_until model_requests_used tool_attempts_used")
        == ("verifying", None, None, 1, 0)
        and planner.fence > intent.intent_fence
    )
    _require(
        _fields(intent, "company_id task_id trace_id run_id attempt_kind state")
        == (
            control.company_id,
            planner.task_id,
            planner.trace_id,
            planner.run_id,
            "model_requests",
            "succeeded",
        )
    )
    _require(
        _fields(held, "company_id task_id action_id state")
        == (control.company_id, planner.task_id, intent.action_id, "reconciled")
        and held.actual_usd is not None
    )
    _require(
        (
            receipt.company_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.action_id,
            receipt.proposal_hash,
            receipt.outcome,
            receipt.receipt_id,
        )
        == (
            control.company_id,
            planner.task_id,
            planner.trace_id,
            intent.action_id,
            intent.proposal_hash,
            "succeeded",
            origin.receipt_id,
        )
    )
    _require(
        len(receipt.artifacts) == 1
        and (receipt.artifacts[0].artifact_id, receipt.artifacts[0].sha256)
        == (origin.artifact_id, origin.artifact_sha256)
    )
