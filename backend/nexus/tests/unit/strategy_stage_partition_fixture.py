"""Three real ORM-shaped rows with supplied typed proof; no DB, protected READ or effects."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership, RegisteredWork
from nexus.company.management.canonical import canonical_sha256
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
from nexus.company.management.plan_registration import registration
from nexus.company.management.plans import RunBinding
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import KINDS, registration_digest
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.strategy_stage_partition_sql import Queries


@dataclass
class Stage:
    admission: StockFlowCycleAdmission
    registry: ModelRegistry
    proof: StrategyCurrentProof
    identity: VerifiedIdentity
    control: CompanyControl
    company: DirectoryCompany
    member: DirectoryMembership
    executions: list[ExecutionWork]
    directories: list[RegisteredWork]
    tables: list[object]
    stored: dict[tuple[type[object], object], object]
    clock: datetime
    session: MagicMock = field(default_factory=MagicMock)
    events: list[ManagementRevisionEvent] = field(default_factory=list)
    privileged: bool = False
    expire_at_family: bool = False
    binding_queries: int = 0

    def all_rows(self) -> list[object]:
        return [
            self.control,
            self.company,
            self.member,
            *self.executions,
            *self.directories,
            *self.tables,
            *self.events,
        ]

    def change(self, change: str) -> None:
        # One >50-line closed negative matrix mutates only this scenario's owned mock rows.
        if change == "hidden_inactive":
            row = deepcopy(self.directories[1])
            row.task_id, row.active = UUID(int=9899), False
            self.directories.append(row)
        elif change == "intermediate":
            self.directories[1].parent_task_id = UUID(int=9899)
            self.executions[1].parent_task_id = UUID(int=9899)
        elif change == "foreign_child":
            self.directories[1].actor_id = UUID(int=9899)
        elif change == "inactive_child":
            self.directories[1].active = False
        elif change == "quota":
            self.executions[1].model_requests_limit += 1
        elif change == "stored_hash":
            self.executions[1].registration_hash = "f" * 64
        elif change == "usd":
            self.directories[1].allocation_usd += Decimal(".01")
        elif change == "delegated_usd":
            self.directories[0].delegated_usd += Decimal(".01")
        elif change == "delegated_tools":
            self.executions[0].tool_attempts_delegated += 1
        elif change == "root_model_used":
            self.executions[0].model_requests_used = 1
        elif change == "root_fence":
            self.executions[0].fence = 1
        elif change == "revision_used":
            self.executions[0].plan_revisions_used = 1
        elif change == "revision_event":
            root = self.admission.procedure
            self.events.append(
                ManagementRevisionEvent(
                    company_id=self.control.company_id,
                    event_id=UUID(int=9800),
                    procedure_id=root.procedure_id,
                    parent_task_id=root.binding.task_id,
                    parent_run_id=root.binding.run_id,
                    previous_plan_revision_id=UUID(int=9801),
                    next_plan_revision_id=UUID(int=9802),
                    owner_decision_id=UUID(int=9803),
                    owner_id=self.control.owner_id,
                    revision_counter=1,
                    recorded_at=self.clock,
                )
            )
        elif change in {"revoked", "decision_hash"}:
            for candidate in self.tables:
                if change == "revoked" and isinstance(candidate, ManagementPlanHead):
                    candidate.state = "revoked"
                elif change == "decision_hash" and isinstance(candidate, ManagementOwnerDecision):
                    candidate.payload_sha256 = "f" * 64
        elif change == "foreign_owner":
            self.identity = self.identity.model_copy(update={"principal_id": UUID(int=9899)})
        elif change == "membership":
            self.member.membership_active = False
        elif change == "privileged":
            self.privileged = True
        elif change == "wrong_producing_plan":
            loaded = self.proof.original
            prepared = loaded.prepared
            bundle = prepared.original
            scope = bundle.snapshot.scope
            snapshot = bundle.snapshot.model_copy(
                update={
                    "scope": scope.model_copy(
                        update={
                            "producing_plan": scope.producing_plan.model_copy(
                                update={"plan_revision_id": UUID(int=9899)}
                            )
                        }
                    )
                }
            )
            self.proof = replace(
                self.proof,
                original=loaded.model_copy(
                    update={
                        "prepared": prepared.model_copy(
                            update={"original": bundle.model_copy(update={"snapshot": snapshot})}
                        )
                    }
                ),
            )
        else:
            assert change == "no_transaction"
            self.session.in_transaction.return_value = False


def execution(
    bound: RunBinding, item: WorkItem, quota: AttemptQuota, parent: UUID | None, fence: int
) -> ExecutionWork:
    request = registration(bound, item, quota)
    values = {
        f"{kind}_{suffix}": getattr(quota, kind) if suffix == "limit" else 0
        for kind in KINDS
        for suffix in ("limit", "used", "delegated")
    }
    return ExecutionWork(
        company_id=bound.company_id,
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
        state="verifying" if parent else "eligible",
        fence=fence,
        segment_number=0,
        **values,
    )


async def stage_case(monkeypatch: pytest.MonkeyPatch) -> Stage:
    # Keep this >50-line single typed data/row scenario coherent; no production gate is patched.
    from nexus.tests.unit.strategy_transition_observation_fixture import transition_case

    case = transition_case()
    admission = case.catalog.cycle_admission
    assert admission is not None
    proof = case.proof
    payload = proof.initial.pair.plan
    reference = proof.original.prepared.original.snapshot.scope.producing_plan
    assert canonical_sha256(payload) == reference.sha256
    root, company_id = admission.procedure, admission.company_id
    identity = proof.initial.sources.credential.identity
    control = CompanyControl(
        company_id=company_id,
        owner_id=identity.principal_id,
        paused=False,
        policy_version="p1",
        price_version="p1",
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(1),
    )
    company = DirectoryCompany(
        company_id=company_id,
        workspace_id=identity.workspace_id,
        owner_id=control.owner_id,
        company_active=True,
        workspace_active=True,
    )
    member = DirectoryMembership(
        company_id=company_id,
        principal_id=identity.principal_id,
        role="owner",
        principal_active=True,
        membership_active=True,
    )
    root_item = WorkItem(
        company_id=company_id,
        task_id=root.binding.task_id,
        trace_id=root.binding.trace_id,
        goal_id=root.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        budget_usd=root.allocation_usd,
        acceptance=("management.non-executing-allocation.v1",),
    )
    specifications = [(root.binding, root_item, root.quota, None, 0)] + [
        (slot.child.binding, slot.work, slot.child.quota, root.binding.task_id, fence)
        for slot, fence in zip(
            admission.slots[:2],
            (proof.author_current_fence, proof.verifier_current_fence),
            strict=True,
        )
    ]
    executions = [execution(*row) for row in specifications]
    directories = [
        RegisteredWork(
            company_id=company_id,
            workspace_id=bound.workspace_id,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            actor_id=bound.actor_id,
            parent_task_id=parent,
            root_task_id=root.binding.task_id,
            allocation_usd=item.budget_usd,
            delegated_usd=Decimal(0),
            active=True,
        )
        for bound, item, _, parent, _ in specifications
    ]
    directories[0].delegated_usd = sum(
        (slot.child.allocation_usd for slot in admission.slots[:2]), Decimal(0)
    )
    for kind in KINDS:
        setattr(
            executions[0],
            f"{kind}_delegated",
            sum(getattr(slot.child.quota, kind) for slot in admission.slots[:2]),
        )
    for row in executions[1:]:
        row.tool_attempts_used = 1
    revision = ManagementPlanRevision(
        company_id=company_id,
        plan_id=reference.plan_id,
        plan_revision_id=reference.plan_revision_id,
        revision=1,
        goal_id=root.goal_id,
        goal_revision_id=admission.goal.revision_id,
        mandate_revision_id=admission.mandate.revision_id,
        sha256=reference.sha256,
        snapshot_json=payload.model_dump_json(),
        proposed_by=control.owner_id,
        recorded_at=case.now,
    )
    decision = ManagementOwnerDecision(
        company_id=company_id,
        decision_id=UUID(int=9700),
        plan_revision_id=reference.plan_revision_id,
        owner_id=control.owner_id,
        kind="approve",
        payload_sha256=reference.sha256,
        reason="Typed fixture approval row",
        recorded_at=case.now,
    )
    head = ManagementPlanHead(
        company_id=company_id,
        plan_id=reference.plan_id,
        current_revision_id=reference.plan_revision_id,
        goal_id=root.goal_id,
        procedure_id=root.procedure_id,
        decision_id=decision.decision_id,
        state="approved",
    )
    procedure = ManagementProcedure(
        company_id=company_id,
        procedure_id=root.procedure_id,
        goal_id=root.goal_id,
        parent_task_id=root.binding.task_id,
        parent_run_id=root.binding.run_id,
        allocation_usd=root.allocation_usd,
        quota_json=root.quota.model_dump_json(),
        binding_json=root.binding.model_dump_json(),
        recorded_at=case.now,
    )
    tasks = [
        ManagementPlanTask(
            company_id=company_id,
            plan_revision_id=reference.plan_revision_id,
            task_id=slot.child.binding.task_id,
            run_id=slot.child.binding.run_id,
            goal_id=root.goal_id,
            procedure_id=root.procedure_id,
            department_id=slot.child.charter.department_id,
            charter_revision_id=slot.child.charter.revision_id,
            allocation_usd=slot.child.allocation_usd,
            quota_json=slot.child.quota.model_dump_json(),
            binding_json=slot.child.binding.model_dump_json(),
            work_sha256=work.registration_hash,
        )
        for slot, work in zip(admission.slots[:2], executions[1:], strict=True)
    ]
    edge = payload.verification[0]
    verification = ManagementVerificationBinding(
        company_id=company_id,
        plan_revision_id=reference.plan_revision_id,
        author_task_id=edge.author_task_id,
        verifier_task_id=edge.verifier_task_id,
        check_recipe=edge.check_recipe,
    )
    tables: list[object] = [revision, decision, head, procedure, *tasks, verification]
    stored: dict[tuple[type[object], object], object] = {
        (CompanyControl, company_id): control,
        (DirectoryCompany, company_id): company,
        (DirectoryMembership, (company_id, identity.principal_id)): member,
        (ManagementPlanRevision, (company_id, reference.plan_revision_id)): revision,
        (ManagementOwnerDecision, (company_id, decision.decision_id)): decision,
        (ManagementPlanHead, (company_id, reference.plan_id)): head,
    }
    for work in executions:
        stored[(ExecutionWork, (company_id, work.task_id))] = work
    for directory in directories:
        stored[(RegisteredWork, (company_id, directory.task_id))] = directory
    for task in tasks:
        stored[(ManagementPlanTask, (company_id, reference.plan_revision_id, task.task_id))] = task
    item = Stage(
        admission,
        case.catalog.models,
        proof,
        identity,
        control,
        company,
        member,
        executions,
        directories,
        tables,
        stored,
        case.now,
    )
    item.session = Queries(item).session
    return item
