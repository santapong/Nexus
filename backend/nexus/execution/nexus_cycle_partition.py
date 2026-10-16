"""Locked current Nexus family facts; no lease, registration, permit or quota replenishment."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.nexus_coding_catalog import (
    NexusAdmission,
    configured_nexus_admission,
    select_configured_nexus_plan,
)
from nexus.company.management.nexus_cycle_admission import NexusStage
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
)
from nexus.company.management.revision_store import (
    plan_record,
)
from nexus.execution.nexus_cycle_facts import _family, _fields, _require, _transition
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import require_runtime_scope
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl


async def _current(
    session: AsyncSession,
    control: CompanyControl,
    admission: NexusAdmission,
    catalog: PlanAdmissionCatalog,
) -> tuple[PlanRevision, ManagementOwnerDecision, NexusStage]:
    head = await session.get(ManagementPlanHead, (control.company_id, admission.plan_id))
    _require(head is not None and head.state == "approved")
    assert head is not None
    row = await session.get(ManagementPlanRevision, (control.company_id, head.current_revision_id))
    _require(row is not None)
    assert row is not None
    record = plan_record(row)
    _require(configured_nexus_admission(catalog) == admission)
    stage = select_configured_nexus_plan(catalog, record.payload)
    _require(stage is not None)
    assert stage is not None
    decision = await session.get(ManagementOwnerDecision, (control.company_id, head.decision_id))
    _require(decision is not None)
    assert decision is not None
    _require(
        _fields(head, "goal_id procedure_id")
        == (admission.goal.goal_id, admission.procedure.procedure_id)
        and _fields(decision, "company_id owner_id kind plan_revision_id payload_sha256")
        == (control.company_id, control.owner_id, "approve", record.plan_revision_id, record.sha256)
    )
    _require(admission.procedure.binding.actor_id == control.owner_id and not control.paused)
    return record, decision, stage


async def read_current_nexus_family_locked(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    *,
    admission: NexusAdmission,
    catalog: PlanAdmissionCatalog,
) -> PlanRevision:
    """Actual caller-owned role; no owner identity is substituted for engineering/verifier."""
    _require(
        session.in_transaction() and control.company_id == work.company_id == admission.company_id
    )
    actual = await session.scalar(
        select(CompanyControl)
        .where(CompanyControl.company_id == control.company_id)
        .with_for_update()
    )
    _require(actual is control)
    actual_work = await session.scalar(
        select(ExecutionWork)
        .where(ExecutionWork.company_id == work.company_id, ExecutionWork.task_id == work.task_id)
        .with_for_update()
    )
    _require(
        actual_work is work
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
            principal_id=work.actor_id,
        ),
        identity,
        allow_inactive=False,
        owner_read=False,
    )
    record, decision, stage = await _current(session, control, admission, catalog)
    directories, executions = await _family(session, control, admission, record, stage)
    _require(directories.get(work.task_id) is registered and executions.get(work.task_id) is work)
    await _transition(session, control, admission, record, decision, stage, executions)
    return record


async def require_nexus_owner_family_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    *,
    admission: NexusAdmission,
    catalog: PlanAdmissionCatalog,
) -> PlanRevision:
    """Owner transition READ only, kept separate from actor execution scope."""
    _require(
        session.in_transaction() and scope.company_id == admission.company_id == control.company_id
    )
    actual = await session.scalar(
        select(CompanyControl)
        .where(CompanyControl.company_id == control.company_id)
        .with_for_update()
    )
    _require(actual is control)
    await require_brain_scope(
        session,
        control,
        BrainReadScope(
            company_id=scope.company_id,
            workspace_id=identity.workspace_id,
            principal_id=scope.principal_id,
            operation_id=scope.operation_id,
            trace_id=scope.trace_id,
        ),
        identity,
        owner=True,
    )
    record, decision, stage = await _current(session, control, admission, catalog)
    _, executions = await _family(session, control, admission, record, stage)
    await _transition(session, control, admission, record, decision, stage, executions)
    return record
