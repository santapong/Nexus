"""Read actual strategy-stage reservations before owner revision; never allocate or execute."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.control_support import db_clock
from nexus.company.management.cycle_admission import (
    validate_stockflow_cycle,
    validate_stockflow_cycle_configuration,
)
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementPlanTask,
    ManagementProcedure,
    ManagementRevisionEvent,
    ManagementVerificationBinding,
)
from nexus.company.management.plan_registration import registration, require_native_task
from nexus.company.management.plans import RunBinding
from nexus.company.management.strategy_stage_partition_support import _root
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.cycle_partition_support import _execution, _require, _same
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import KINDS
from nexus.harness.journal_models import CompanyControl

if TYPE_CHECKING:
    from nexus.company.management.lifecycle import PlanRevision
    from nexus.company.management.plan_support import CurrentPlanBinding
    from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof


def _proof_time(proof: StrategyCurrentProof, identity: VerifiedIdentity, now: datetime) -> None:
    for protection in (proof.initial, proof.current):
        credential = protection.sources.credential
        _require(isinstance(credential, AuthenticatedWorkerIdentity))
        _require(credential.identity == identity)
        credential.require_time(now)
    proof.require_time(now)


async def _current_plan(
    session: AsyncSession,
    control: CompanyControl,
    admission: StockFlowCycleAdmission,
    registry: ModelRegistry,
    proof: StrategyCurrentProof,
) -> tuple[PlanRevision, dict[UUID, CurrentPlanBinding]]:
    from nexus.company.management.plan_store import ManagementPlanStore
    from nexus.company.management.revision_store import plan_record, plan_reference

    original = proof.original.prepared.original.snapshot
    _require(original.company_id == admission.company_id and original.scope.goal == admission.goal)
    bindings = {}
    for slot in admission.slots[:2]:
        key = slot.child.binding.task_id
        binding = await ManagementPlanStore.current_binding(session, admission.company_id, key)
        _require(binding is not None)
        assert binding is not None
        _require(
            binding.child == slot.child
            and binding.work == slot.work
            and binding.procedure_id == admission.procedure.procedure_id
            and binding.plan == original.scope.producing_plan
        )
        bindings[key] = binding
    reference = next(iter(bindings.values())).plan
    row = await session.get(
        ManagementPlanRevision, (admission.company_id, reference.plan_revision_id)
    )
    _require(row is not None)
    assert row is not None
    record = plan_record(row)
    selected = validate_stockflow_cycle(admission, registry, record.payload)
    _require(
        selected is not None
        and selected.stage == "strategy"
        and reference == plan_reference(record)
        and reference.revision == 1
        and proof.initial.pair.plan == proof.current.pair.plan == record.payload
        and original.scope.author_registration_sha256
        == bindings[admission.slots[0].child.binding.task_id].work_sha256
        and (original.scope.author, original.scope.verifier)
        == tuple(slot.child.binding for slot in admission.slots[:2])
        and original.author_registration
        == registration(
            admission.slots[0].child.binding,
            admission.slots[0].work,
            admission.slots[0].child.quota,
        )
    )
    return record, bindings


async def _approved(
    session: AsyncSession,
    control: CompanyControl,
    admission: StockFlowCycleAdmission,
    record: PlanRevision,
    now: datetime,
) -> None:
    # Keep this >50-line original owner/procedure/no-revision read boundary cohesive.
    head = await session.get(ManagementPlanHead, (admission.company_id, record.plan_id))
    _require(head is not None)
    assert head is not None
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
    rows = tuple(
        (
            await session.scalars(
                select(ManagementOwnerDecision)
                .where(
                    ManagementOwnerDecision.company_id == admission.company_id,
                    ManagementOwnerDecision.plan_revision_id == record.plan_revision_id,
                    ManagementOwnerDecision.kind == "approve",
                )
                .limit(2)
            )
        ).all()
    )
    _require(len(rows) == 1)
    row = rows[0]
    _require(
        _same(
            row,
            "decision_id owner_id kind plan_revision_id payload_sha256",
            (
                head.decision_id,
                control.owner_id,
                "approve",
                record.plan_revision_id,
                record.sha256,
            ),
        )
        and record.recorded_at <= row.recorded_at <= now
    )
    root = admission.procedure
    procedure = await session.scalar(
        select(ManagementProcedure).where(
            ManagementProcedure.company_id == admission.company_id,
            ManagementProcedure.goal_id == admission.goal.goal_id,
        )
    )
    _require(procedure is not None)
    assert procedure is not None
    _require(
        _same(
            procedure,
            "procedure_id parent_task_id parent_run_id allocation_usd",
            (
                root.procedure_id,
                root.binding.task_id,
                root.binding.run_id,
                root.allocation_usd,
            ),
        )
        and RunBinding.model_validate_json(procedure.binding_json) == root.binding
        and AttemptQuota.model_validate_json(procedure.quota_json) == root.quota
    )
    events = tuple(
        (
            await session.scalars(
                select(ManagementRevisionEvent)
                .where(
                    ManagementRevisionEvent.company_id == admission.company_id,
                    ManagementRevisionEvent.procedure_id == root.procedure_id,
                )
                .limit(1)
            )
        ).all()
    )
    _require(not events)


async def _family(
    session: AsyncSession,
    admission: StockFlowCycleAdmission,
) -> tuple[dict[UUID, RegisteredWork], dict[UUID, ExecutionWork]]:
    root = admission.procedure.binding.task_id
    expected = {root, *(slot.child.binding.task_id for slot in admission.slots[:2])}
    directories = tuple(
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
    executions = tuple(
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
    _require(len(directories) == len(executions) == 3)
    _require(
        {row.task_id for row in directories} == {row.task_id for row in executions} == expected
    )
    return {row.task_id: row for row in directories}, {row.task_id: row for row in executions}


async def _children(
    session: AsyncSession,
    admission: StockFlowCycleAdmission,
    record: PlanRevision,
    bindings: dict[UUID, CurrentPlanBinding],
    directories: dict[UUID, RegisteredWork],
    executions: dict[UUID, ExecutionWork],
    proof: StrategyCurrentProof,
) -> None:
    # Keep this >50-line exact native row, child allocation and verification-edge check together.
    natives = tuple(
        (
            await session.scalars(
                select(ManagementPlanTask)
                .where(
                    ManagementPlanTask.company_id == admission.company_id,
                    ManagementPlanTask.plan_revision_id == record.plan_revision_id,
                )
                .limit(3)
            )
        ).all()
    )
    _require(len(natives) == 2)
    native = {row.task_id: row for row in natives}
    _require(set(native) == set(bindings))
    for slot, fence in zip(
        admission.slots[:2], (proof.author_current_fence, proof.verifier_current_fence), strict=True
    ):
        child, bound = slot.child, slot.child.binding
        work, directory = executions[bound.task_id], directories[bound.task_id]
        require_native_task(native[bound.task_id], work, child, record.payload)
        _execution(work, registration(bound, slot.work, child.quota))
        _require(
            _same(
                directory,
                "company_id workspace_id actor_id trace_id parent_task_id root_task_id "
                "allocation_usd delegated_usd active",
                (
                    admission.company_id,
                    bound.workspace_id,
                    bound.actor_id,
                    bound.trace_id,
                    admission.procedure.binding.task_id,
                    admission.procedure.binding.task_id,
                    child.allocation_usd,
                    Decimal(0),
                    True,
                ),
            )
        )
        _require(
            work.parent_task_id == admission.procedure.binding.task_id
            and work.workspace_id == bound.workspace_id
            and work.actor_id == bound.actor_id
            and work.fence == fence
            and work.state not in {"blocked", "outcome_unknown"}
            and bindings[bound.task_id].work_sha256 == work.registration_hash
        )
        _require(all(getattr(work, f"{kind}_delegated") == 0 for kind in KINDS))
    edges = tuple(
        (
            await session.scalars(
                select(ManagementVerificationBinding)
                .where(
                    ManagementVerificationBinding.company_id == admission.company_id,
                    ManagementVerificationBinding.plan_revision_id == record.plan_revision_id,
                )
                .limit(2)
            )
        ).all()
    )
    _require(len(edges) == 1)
    expected = record.payload.verification[0]
    _require(
        _same(
            edges[0],
            "author_task_id verifier_task_id check_recipe",
            (
                expected.author_task_id,
                expected.verifier_task_id,
                expected.check_recipe,
            ),
        )
    )


async def require_strategy_stage_partition_locked(
    session: AsyncSession,
    control: CompanyControl,
    identity: VerifiedIdentity,
    *,
    admission: StockFlowCycleAdmission,
    registry: ModelRegistry,
    proof: StrategyCurrentProof,
) -> None:
    """Read only the original root/S/SV family inside the caller's company-first transaction."""
    from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof

    _require(session.in_transaction() and isinstance(proof, StrategyCurrentProof))
    checked = validate_stockflow_cycle_configuration(admission, registry)
    _require(
        control.company_id == checked.company_id
        and not control.paused
        and identity.principal_id == control.owner_id
        and identity.workspace_id == checked.procedure.binding.workspace_id
    )
    actual = await session.scalar(
        select(CompanyControl)
        .where(
            CompanyControl.company_id == checked.company_id,
        )
        .with_for_update()
    )
    _require(actual is control)
    await require_strategy_application_role(session)
    scope = BrainReadScope(
        company_id=checked.company_id,
        workspace_id=identity.workspace_id,
        principal_id=identity.principal_id,
        operation_id=uuid5(checked.procedure.procedure_id, "strategy-stage-partition:v1"),
        trace_id=checked.procedure.binding.trace_id,
    )
    await require_brain_scope(session, control, scope, identity, owner=True)
    now = await db_clock(session)
    _proof_time(proof, identity, now)
    record, bindings = await _current_plan(session, control, checked, registry, proof)
    await _approved(session, control, checked, record, now)
    directories, executions = await _family(session, checked)
    root = checked.procedure.binding.task_id
    _root(checked, directories[root], executions[root])
    await _children(session, checked, record, bindings, directories, executions, proof)
    await require_brain_scope(session, control, scope, identity, owner=True)
    _proof_time(proof, identity, await db_clock(session))
