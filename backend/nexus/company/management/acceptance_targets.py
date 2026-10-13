"""Exact current governance, charter and independently registered work target materialization."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.company.directory_models import DirectoryMembership, RegisteredWork, WorkPrincipal
from nexus.company.directory_store import _lineage_active
from nexus.company.management.acceptance_errors import require_acceptance as denied
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalDefinition
from nexus.company.management.governance_models import (
    ManagementCharterHead,
    ManagementCharterRevision,
    ManagementGoalHead,
    ManagementGoalRevision,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.company.management.plan_models import ManagementPlanTask
from nexus.company.management.plans import ChildAllocation, PlanPayload, RunBinding
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_models import CompanyControl


async def current_governance(
    session: AsyncSession,
    control: CompanyControl,
    payload: PlanPayload,
) -> None:
    company = payload.company_id
    mandate = await session.get(ManagementMandateRevision, (company, payload.mandate.revision_id))
    mandate_head = await session.get(ManagementMandateHead, company)
    goal = await session.get(ManagementGoalRevision, (company, payload.goal.revision_id))
    goal_head = await session.get(ManagementGoalHead, (company, payload.goal.goal_id))
    denied(
        mandate is not None
        and mandate_head is not None
        and mandate_head.active
        and mandate_head.current_revision_id == mandate.revision_id
        and mandate.owner_id == control.owner_id
        and (mandate.version, mandate.sha256) == (payload.mandate.version, payload.mandate.sha256)
    )
    assert mandate is not None
    content = CompanyMandate.model_validate_json(mandate.payload_json)
    denied(canonical_sha256(content) == mandate.sha256 and content.owner_id == control.owner_id)
    denied(
        goal is not None
        and goal_head is not None
        and goal_head.active
        and goal_head.current_revision_id == goal.revision_id
        and (goal.version, goal.sha256, goal.mandate_revision_id)
        == (payload.goal.version, payload.goal.sha256, mandate.revision_id)
    )
    assert goal is not None
    definition = GoalDefinition.model_validate_json(goal.payload_json)
    denied(
        canonical_sha256(definition) == goal.sha256
        and definition.mandate == payload.mandate
        and definition.company_id == company
        and definition.goal_id == payload.goal.goal_id
        and definition.owner_id == goal.responsible_id
    )
    responsible = await session.get(DirectoryMembership, (company, goal.responsible_id))
    denied(
        responsible is not None and responsible.principal_active and responsible.membership_active
    )


async def current_work(
    session: AsyncSession,
    control: CompanyControl,
    payload: PlanPayload,
    revision_id: UUID,
    task_id: UUID,
) -> tuple[ExecutionWork, ChildAllocation, DepartmentCharter]:
    company = payload.company_id
    selected = next((row for row in payload.children if row.binding.task_id == task_id), None)
    native = await session.get(ManagementPlanTask, (company, revision_id, task_id))
    work = await session.get(ExecutionWork, (company, task_id))
    registered = await session.get(RegisteredWork, (company, task_id))
    denied(
        selected is not None and native is not None and work is not None and registered is not None
    )
    assert (
        selected is not None and native is not None and work is not None and registered is not None
    )
    check_work_binding(work, registered, native, selected, payload)
    member = await session.get(DirectoryMembership, (company, selected.binding.actor_id))
    denied(
        member is not None
        and member.principal_active
        and member.membership_active
        and member.role != "viewer"
        and not (member.role == "owner" and member.principal_id != control.owner_id)
        and await _lineage_active(session, registered)
    )
    denied(
        await session.get(WorkPrincipal, (company, task_id, selected.binding.actor_id)) is not None
    )
    return work, selected, await current_charter(session, payload, selected)


def check_work_binding(
    work: ExecutionWork,
    registered: RegisteredWork,
    native: ManagementPlanTask,
    selected: ChildAllocation,
    payload: PlanPayload,
) -> None:
    expected = selected.binding
    denied(
        RunBinding.model_validate_json(native.binding_json) == expected
        and snapshot(work).registration.work
        == next(row for row in payload.plan.items if row.task_id == work.task_id)
    )
    denied(
        RunBinding(
            company_id=work.company_id,
            workspace_id=work.workspace_id,
            actor_id=work.actor_id,
            task_id=work.task_id,
            trace_id=work.trace_id,
            run_id=work.run_id,
            workflow_name=work.workflow_name,
            workflow_version=work.workflow_version,
            model_profile=work.model_profile,
            model_registry_version=work.model_registry_version,
        )
        == expected
    )
    denied(
        (registered.actor_id, registered.workspace_id, registered.trace_id)
        == (expected.actor_id, expected.workspace_id, expected.trace_id)
    )
    denied(
        native.work_sha256 == work.registration_hash
        and native.charter_revision_id == selected.charter.revision_id
        and native.department_id == selected.charter.department_id
        and native.procedure_id == payload.procedure.procedure_id
    )


async def current_charter(
    session: AsyncSession,
    payload: PlanPayload,
    selected: ChildAllocation,
) -> DepartmentCharter:
    ref = selected.charter
    head = await session.get(ManagementCharterHead, (payload.company_id, ref.department_id))
    revision = await session.get(ManagementCharterRevision, (payload.company_id, ref.revision_id))
    denied(
        head is not None
        and head.active
        and head.current_revision_id == ref.revision_id
        and revision is not None
        and revision.mandate_revision_id == payload.mandate.revision_id
        and (revision.department_id, revision.version, revision.sha256)
        == (ref.department_id, ref.version, ref.sha256)
    )
    assert revision is not None
    content = DepartmentCharter.model_validate_json(revision.payload_json)
    denied(canonical_sha256(content) == ref.sha256)
    return content
