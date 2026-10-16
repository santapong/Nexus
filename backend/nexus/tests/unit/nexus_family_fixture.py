"""Actual ORM/registration shapes; only existing SQL/governance delivery is supplied."""

from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import pytest
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.nexus_cycle_admission import NexusCycleAdmission, NexusStage
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
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
from nexus.company.management.revision_store import plan_reference
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import KINDS, registration_digest
from nexus.harness.journal_models import CompanyControl, CostHold
from nexus.tests.unit.nexus_cycle_fixture import NOW, base, case, key, origin


@dataclass
class Family:
    admission: NexusCycleAdmission
    catalog: PlanAdmissionCatalog
    session: AsyncSession
    control: CompanyControl
    work: ExecutionWork
    identity: VerifiedIdentity
    executions: list[ExecutionWork]
    directories: list[RegisteredWork]
    stored: dict[tuple[type[object], object], object]
    events: list[ManagementRevisionEvent]
    bindings: dict[UUID, CurrentPlanBinding]


def family(monkeypatch: pytest.MonkeyPatch, stage: NexusStage = "execution") -> Family:
    from nexus.execution import nexus_cycle_facts as facts
    from nexus.execution import nexus_cycle_partition as gate

    admission, catalog = case()
    root = admission.procedure
    company = admission.company_id
    control = CompanyControl(
        company_id=company,
        owner_id=root.binding.actor_id,
        policy_version="p1",
        price_version="p1",
        paused=False,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(1),
    )
    initial = base(admission)
    payload = admission.payload(stage, origin=origin(admission) if stage == "execution" else None)
    digest = canonical_sha256(payload)
    revision = type(initial)(
        company_id=company,
        plan_id=admission.plan_id,
        plan_revision_id=uuid5(admission.plan_id, f"plan:{payload.plan.revision}:{digest}"),
        revision=payload.plan.revision,
        sha256=digest,
        payload=payload,
        proposed_by=control.owner_id,
        recorded_at=NOW,
    )
    records = (initial, revision) if stage == "execution" else (initial,)
    stored: dict[tuple[type[object], object], object] = {}
    decisions = []
    for record in records:
        row = ManagementPlanRevision(
            company_id=company,
            plan_revision_id=record.plan_revision_id,
            plan_id=record.plan_id,
            revision=record.revision,
            goal_id=admission.goal.goal_id,
            goal_revision_id=admission.goal.revision_id,
            mandate_revision_id=admission.mandate.revision_id,
            sha256=record.sha256,
            snapshot_json=record.payload.model_dump_json(),
            proposed_by=control.owner_id,
            recorded_at=NOW,
        )
        decision = ManagementOwnerDecision(
            company_id=company,
            decision_id=key("decision-" + str(record.revision)),
            plan_revision_id=record.plan_revision_id,
            owner_id=control.owner_id,
            kind="approve",
            payload_sha256=record.sha256,
            reason="Synthetic exact owner-decision row",
            recorded_at=NOW,
        )
        stored[(ManagementPlanRevision, (company, record.plan_revision_id))] = row
        stored[(ManagementOwnerDecision, (company, decision.decision_id))] = decision
        decisions.append(decision)
    stored[(ManagementPlanHead, (company, revision.plan_id))] = ManagementPlanHead(
        company_id=company,
        plan_id=revision.plan_id,
        current_revision_id=revision.plan_revision_id,
        goal_id=admission.goal.goal_id,
        procedure_id=root.procedure_id,
        decision_id=decisions[-1].decision_id,
        state="approved",
    )
    root_item = WorkItem(
        company_id=company,
        task_id=root.binding.task_id,
        trace_id=root.binding.trace_id,
        goal_id=admission.goal.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        acceptance=("management.non-executing-allocation.v1",),
        budget_usd=root.allocation_usd,
    )
    specs: list[tuple[RunBinding, WorkItem, AttemptQuota, UUID | None]] = [
        (root.binding, root_item, root.quota, None)
    ]
    slots = admission.slots[:1] if stage == "planning" else admission.slots
    specs += [
        (slot.child.binding, slot.work, slot.child.quota, root.binding.task_id) for slot in slots
    ]
    executions = []
    directories = []
    bindings = {}
    for binding, item, quota, parent in specs:
        request = registration(binding, item, quota)
        values = {
            f"{kind}_{suffix}": getattr(quota, kind) if suffix == "limit" else 0
            for kind in KINDS
            for suffix in ("limit", "used", "delegated")
        }
        actual = ExecutionWork(
            company_id=company,
            task_id=binding.task_id,
            trace_id=binding.trace_id,
            actor_id=binding.actor_id,
            workspace_id=binding.workspace_id,
            parent_task_id=parent,
            run_id=binding.run_id,
            workflow_name=binding.workflow_name,
            workflow_version=binding.workflow_version,
            model_profile=binding.model_profile,
            model_registry_version=binding.model_registry_version,
            registration_json=request.model_dump_json(),
            registration_hash=registration_digest(request),
            state="eligible",
            fence=0,
            segment_number=0,
            **values,
        )
        directory = RegisteredWork(
            company_id=company,
            task_id=binding.task_id,
            trace_id=binding.trace_id,
            actor_id=binding.actor_id,
            workspace_id=binding.workspace_id,
            parent_task_id=parent,
            root_task_id=root.binding.task_id,
            allocation_usd=item.budget_usd,
            delegated_usd=Decimal(0),
            active=True,
        )
        executions.append(actual)
        directories.append(directory)
        stored[(ExecutionWork, (company, binding.task_id))] = actual
        if parent:
            slot = next(s for s in slots if s.work.task_id == binding.task_id)
            task_row = ManagementPlanTask(
                company_id=company,
                plan_revision_id=revision.plan_revision_id,
                task_id=binding.task_id,
                run_id=binding.run_id,
                goal_id=admission.goal.goal_id,
                procedure_id=root.procedure_id,
                department_id=slot.child.charter.department_id,
                charter_revision_id=slot.child.charter.revision_id,
                allocation_usd=slot.child.allocation_usd,
                quota_json=quota.model_dump_json(),
                binding_json=binding.model_dump_json(),
                work_sha256=actual.registration_hash,
            )
            stored[(ManagementPlanTask, (company, revision.plan_revision_id, binding.task_id))] = (
                task_row
            )
            bindings[binding.task_id] = CurrentPlanBinding(
                company_id=company,
                plan=plan_reference(revision),
                child=slot.child,
                work=item,
                work_sha256=actual.registration_hash,
                procedure_id=root.procedure_id,
            )
    for kind in KINDS:
        setattr(
            executions[0],
            f"{kind}_delegated",
            sum(getattr(slot.child.quota, kind) for slot in slots),
        )
    executions[0].plan_revisions_used = int(stage == "execution")
    directories[0].delegated_usd = sum((slot.child.allocation_usd for slot in slots), Decimal(0))
    procedure = ManagementProcedure(
        company_id=company,
        procedure_id=root.procedure_id,
        goal_id=root.goal_id,
        parent_task_id=root.binding.task_id,
        parent_run_id=root.binding.run_id,
        allocation_usd=root.allocation_usd,
        quota_json=root.quota.model_dump_json(),
        binding_json=root.binding.model_dump_json(),
        recorded_at=NOW,
    )
    events = []
    if stage == "execution":
        planner = executions[1]
        planner.model_requests_used = 1
        planner.fence = 2
        planner.state = "verifying"
        planner.segment_number = 1
        planner.segment_id = key("planning-segment")
        ref = origin(admission)
        receipt = ActionReceipt(
            company_id=company,
            receipt_id=ref.receipt_id,
            action_id=ref.action_id,
            task_id=planner.task_id,
            trace_id=planner.trace_id,
            proposal_hash="a" * 64,
            outcome="succeeded",
            recorded_at=NOW,
            artifacts=(
                ArtifactRef(
                    company_id=company,
                    artifact_id=ref.artifact_id,
                    reference="fixture:unexecuted-model-envelope",
                    sha256=ref.artifact_sha256,
                    revision="model-result-envelope-v1",
                    allowed_principals=(control.owner_id,),
                ),
            ),
        )
        stored[(EffectIntent, (company, ref.action_id))] = EffectIntent(
            company_id=company,
            action_id=ref.action_id,
            task_id=planner.task_id,
            trace_id=planner.trace_id,
            run_id=planner.run_id,
            proposal_hash="a" * 64,
            intent_fence=1,
            attempt_kind="model_requests",
            state="succeeded",
            created_at=NOW,
            receipt_json=receipt.model_dump_json(),
            verification_json=None,
        )
        stored[(CostHold, ref.action_id)] = CostHold(
            company_id=company,
            action_id=ref.action_id,
            task_id=planner.task_id,
            day=NOW.date(),
            amount_usd=Decimal(".01"),
            actual_usd=Decimal(".001"),
            state="reconciled",
        )
        events.append(
            ManagementRevisionEvent(
                company_id=company,
                event_id=key("revision-event"),
                procedure_id=root.procedure_id,
                parent_task_id=root.binding.task_id,
                parent_run_id=root.binding.run_id,
                previous_plan_revision_id=initial.plan_revision_id,
                next_plan_revision_id=revision.plan_revision_id,
                owner_decision_id=decisions[-1].decision_id,
                owner_id=control.owner_id,
                revision_counter=1,
                recorded_at=NOW,
            )
        )
    selected = executions[1 if stage == "planning" else 2]
    mock = MagicMock(spec=AsyncSession)
    session = cast(AsyncSession, mock)
    mock.in_transaction.return_value = True

    async def get(model: type[object], selector: object) -> object | None:
        return stored.get((model, selector))

    async def scalar(statement: Select[tuple[object]]) -> object | None:
        description = statement.column_descriptions[0]
        entity = description.get("entity")
        if entity is CompanyControl:
            return control
        if entity is ExecutionWork:
            return selected
        if entity is ManagementProcedure:
            return procedure
        raise AssertionError("Unexpected SQL scalar delivery")

    async def scalars(statement: Select[tuple[object]]) -> MagicMock:
        entity = statement.column_descriptions[0].get("entity")
        rows = (
            directories
            if entity is RegisteredWork
            else executions
            if entity is ExecutionWork
            else events
            if entity is ManagementRevisionEvent
            else decisions[:1]
            if entity is ManagementOwnerDecision
            else []
        )
        return MagicMock(all=MagicMock(return_value=rows))

    mock.get = AsyncMock(side_effect=get)
    mock.scalar = AsyncMock(side_effect=scalar)
    mock.scalars = AsyncMock(side_effect=scalars)
    monkeypatch.setattr(
        ManagementPlanStore,
        "current_binding",
        AsyncMock(side_effect=lambda session, company, task: bindings.get(task)),
    )
    monkeypatch.setattr(facts, "require_current_governance", AsyncMock())
    monkeypatch.setattr(facts, "_actor", AsyncMock())
    monkeypatch.setattr(
        gate,
        "require_runtime_scope",
        AsyncMock(return_value=next(row for row in directories if row.task_id == selected.task_id)),
    )
    monkeypatch.setattr(gate, "require_brain_scope", AsyncMock())
    identity = VerifiedIdentity(principal_id=selected.actor_id, workspace_id=selected.workspace_id)
    return Family(
        admission,
        catalog,
        session,
        control,
        selected,
        identity,
        executions,
        directories,
        stored,
        events,
        bindings,
    )
