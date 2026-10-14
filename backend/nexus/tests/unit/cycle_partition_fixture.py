"""Real ORM/contract shapes with mocked reads only; no database or authority proof."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementPlanTask,
    ManagementProcedure,
    ManagementRevisionEvent,
)
from nexus.company.management.plan_registration import registration
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.plans import RunBinding
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import KINDS, registration_digest
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.cycle_admission_fixture import Cycle, cycle, declared

NOW = datetime(2026, 10, 15, tzinfo=UTC)


@dataclass
class Partition:
    cycle: Cycle
    session: MagicMock
    control: CompanyControl
    work: ExecutionWork
    identity: VerifiedIdentity
    executions: list[ExecutionWork]
    directories: list[RegisteredWork]
    bindings: dict[UUID, CurrentPlanBinding]
    stored: dict[tuple[type[object], object], object]
    procedure: ManagementProcedure
    events: list[ManagementRevisionEvent]
    decisions: list[ManagementOwnerDecision]


def partition(monkeypatch: pytest.MonkeyPatch) -> Partition:
    """One coherent pure row scenario; membership/governance calls are mocked, not proved."""
    # This >50-line fixture keeps all twelve actual-shaped identities and both revisions coherent.
    from nexus.execution import cycle_partition_checks as module

    item = cycle()
    slots = list(item.admission.slots)
    sender = slots[-1].child
    slots[-1] = slots[-1].model_copy(
        update={
            "child": sender.model_copy(
                update={"binding": sender.binding.model_copy(update={"actor_id": UUID(int=3)})}
            )
        }
    )
    admission = item.admission.model_copy(update={"slots": tuple(slots)})
    item = Cycle(admission, item.registry, declared(admission, 1), declared(admission, 2))
    root = item.admission.procedure
    company = item.admission.company_id
    control = CompanyControl(
        company_id=company,
        owner_id=UUID(int=3),
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(1),
        policy_version="p1",
        price_version="p1",
        paused=False,
    )
    root_work = WorkItem(
        company_id=company,
        task_id=root.binding.task_id,
        trace_id=root.binding.trace_id,
        goal_id=root.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        acceptance=("management.non-executing-allocation.v1",),
        budget_usd=root.allocation_usd,
    )
    specifications: list[tuple[RunBinding, WorkItem, AttemptQuota, UUID | None, Decimal]] = [
        (root.binding, root_work, root.quota, None, root.allocation_usd)
    ]
    specifications += [
        (
            slot.child.binding,
            slot.work,
            slot.child.quota,
            root.binding.task_id,
            slot.child.allocation_usd,
        )
        for slot in item.admission.slots
    ]
    executions, directories = [], []
    for bound, work, quota, parent, usd in specifications:
        request = registration(bound, work, quota)
        values = {
            f"{kind}_{suffix}": getattr(quota, kind) if suffix == "limit" else 0
            for kind in KINDS
            for suffix in ("limit", "used", "delegated")
        }
        executions.append(
            ExecutionWork(
                company_id=company,
                task_id=bound.task_id,
                trace_id=bound.trace_id,
                actor_id=bound.actor_id,
                workspace_id=bound.workspace_id,
                parent_task_id=parent,
                run_id=bound.run_id,
                registration_json=request.model_dump_json(),
                registration_hash=registration_digest(request),
                workflow_name=bound.workflow_name,
                workflow_version=bound.workflow_version,
                model_profile=bound.model_profile,
                model_registry_version=bound.model_registry_version,
                state="eligible",
                fence=0,
                segment_number=0,
                **values,
            )
        )
        directories.append(
            RegisteredWork(
                company_id=company,
                task_id=bound.task_id,
                trace_id=bound.trace_id,
                actor_id=bound.actor_id,
                workspace_id=bound.workspace_id,
                parent_task_id=parent,
                root_task_id=root.binding.task_id,
                allocation_usd=usd,
                delegated_usd=Decimal(0),
                active=True,
            )
        )
    executions[0].model_requests_delegated = 3
    executions[0].tool_attempts_delegated = 11
    executions[0].plan_revisions_used = 1
    executions[1].model_requests_used = executions[1].tool_attempts_used = 1
    directories[0].delegated_usd = Decimal(".96")
    procedure = ManagementProcedure(
        company_id=company,
        procedure_id=root.procedure_id,
        goal_id=root.goal_id,
        parent_task_id=root.binding.task_id,
        parent_run_id=root.binding.run_id,
        allocation_usd=root.allocation_usd,
        binding_json=root.binding.model_dump_json(),
        quota_json=root.quota.model_dump_json(),
        recorded_at=NOW,
    )
    stored: dict[tuple[type[object], object], object] = {}
    revisions, decisions = [], []
    for index, payload in enumerate((item.strategy, item.full), 1):
        revision = ManagementPlanRevision(
            company_id=company,
            plan_revision_id=UUID(int=700 + index),
            plan_id=payload.plan.plan_id,
            revision=index,
            goal_id=payload.goal.goal_id,
            goal_revision_id=payload.goal.revision_id,
            mandate_revision_id=payload.mandate.revision_id,
            sha256=canonical_sha256(payload),
            snapshot_json=payload.model_dump_json(),
            proposed_by=control.owner_id,
            recorded_at=NOW,
        )
        decision = ManagementOwnerDecision(
            company_id=company,
            decision_id=UUID(int=800 + index),
            plan_revision_id=revision.plan_revision_id,
            owner_id=control.owner_id,
            kind="approve",
            payload_sha256=revision.sha256,
            reason="Pure exact prior owner decision shape",
            recorded_at=NOW,
        )
        revisions.append(revision)
        decisions.append(decision)
        stored[(ManagementPlanRevision, (company, revision.plan_revision_id))] = revision
        stored[(ManagementOwnerDecision, (company, decision.decision_id))] = decision
    latest = revisions[1]
    head = ManagementPlanHead(
        company_id=company,
        plan_id=latest.plan_id,
        current_revision_id=latest.plan_revision_id,
        goal_id=root.goal_id,
        procedure_id=root.procedure_id,
        decision_id=decisions[1].decision_id,
        state="approved",
    )
    stored[(ManagementPlanHead, (company, latest.plan_id))] = head
    plan_ref = PlanRevisionRef(
        company_id=company,
        plan_id=latest.plan_id,
        plan_revision_id=latest.plan_revision_id,
        revision=2,
        sha256=latest.sha256,
    )
    bindings = {}
    for slot, actual in zip(item.admission.slots, executions[1:], strict=True):
        child = slot.child
        bound = child.binding
        native = ManagementPlanTask(
            company_id=company,
            plan_revision_id=latest.plan_revision_id,
            task_id=bound.task_id,
            run_id=bound.run_id,
            goal_id=root.goal_id,
            procedure_id=root.procedure_id,
            department_id=child.charter.department_id,
            charter_revision_id=child.charter.revision_id,
            allocation_usd=child.allocation_usd,
            quota_json=child.quota.model_dump_json(),
            binding_json=bound.model_dump_json(),
            work_sha256=actual.registration_hash,
        )
        stored[(ManagementPlanTask, (company, latest.plan_revision_id, bound.task_id))] = native
        bindings[bound.task_id] = CurrentPlanBinding(
            company_id=company,
            plan=plan_ref,
            child=child,
            work=slot.work,
            work_sha256=actual.registration_hash,
            procedure_id=root.procedure_id,
        )
    event = ManagementRevisionEvent(
        company_id=company,
        event_id=UUID(int=900),
        procedure_id=root.procedure_id,
        parent_task_id=root.binding.task_id,
        parent_run_id=root.binding.run_id,
        previous_plan_revision_id=revisions[0].plan_revision_id,
        next_plan_revision_id=latest.plan_revision_id,
        owner_decision_id=decisions[1].decision_id,
        owner_id=control.owner_id,
        revision_counter=1,
        recorded_at=NOW,
    )
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    result = Partition(
        item,
        session,
        control,
        executions[3],
        VerifiedIdentity(
            principal_id=executions[3].actor_id, workspace_id=executions[3].workspace_id
        ),
        executions,
        directories,
        bindings,
        stored,
        procedure,
        [event],
        decisions,
    )

    async def scalar(statement: object) -> object:
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        return {
            CompanyControl: result.control,
            ExecutionWork: result.work,
            ManagementProcedure: result.procedure,
        }[entity]

    async def scalars(statement: object) -> MagicMock:
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        rows = {
            ExecutionWork: result.executions,
            RegisteredWork: result.directories,
            ManagementRevisionEvent: result.events,
            ManagementOwnerDecision: result.decisions[:1],
        }[entity]
        captured = MagicMock()
        captured.all.return_value = rows
        return captured

    async def get(model: type[object], key: object) -> object:
        return result.stored.get((model, key))

    async def binding(_: AsyncSession, __: UUID, task: UUID) -> CurrentPlanBinding | None:
        return result.bindings.get(task)

    session.scalar = AsyncMock(side_effect=scalar)
    session.scalars = AsyncMock(side_effect=scalars)
    session.get = AsyncMock(side_effect=get)
    for name in ("add", "add_all", "flush", "commit", "begin"):
        setattr(
            session,
            name,
            MagicMock(side_effect=AssertionError("Read-only helper attempted " + name)),
        )
    monkeypatch.setattr(ManagementPlanStore, "current_binding", binding)
    monkeypatch.setattr(ManagementPlanStore, "managed_kind", AsyncMock(return_value="procedure"))
    monkeypatch.setattr(module, "require_runtime_scope", AsyncMock(return_value=directories[3]))
    monkeypatch.setattr(module, "require_current_governance", AsyncMock())
    return result
