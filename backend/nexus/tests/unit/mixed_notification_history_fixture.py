"""Predicate-faithful SQL delivery over actual ORM shapes; no live native permission proof."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import (
    DirectoryCompany,
    DirectoryMembership,
    RegisteredWork,
    WorkPrincipal,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanRevision,
    ManagementPlanTask,
    ManagementProcedure,
    ManagementRevisionEvent,
    ManagementVerificationBinding,
)
from nexus.company.management.plan_registration import registration
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.ledger_rules import stable_idempotency_key
from nexus.company.notifications.proposals import NOTIFICATION_TOOL, NotificationDispatchParameters
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import KINDS
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.mixed_notification_fixture import MixedCase, mixed_case
from nexus.tests.unit.strategy_stage_partition_fixture import Stage, execution
from nexus.tests.unit.strategy_stage_partition_sql import Queries


@dataclass
class HistoryCase:
    mixed: MixedCase
    control: CompanyControl
    work: ExecutionWork
    command: SegmentCommand
    rows: list[Any]
    stored: dict[tuple[type[object], object], object]
    clock: datetime
    session: Any = None
    privileged: bool = False
    binding_queries: int = 0
    expire_at_family: bool = False

    def all_rows(self) -> list[Any]:
        return self.rows


def history_case(root: Path) -> HistoryCase:
    # One >50-line linked metadata fixture; every product query still executes against predicates.
    m = mixed_case(root)
    data = m.data
    admission = m.reads.facts.catalog.cycle_admission
    assert admission is not None
    rootdef = admission.procedure
    bound = admission.slots[-1].child.binding
    control = CompanyControl(company_id=bound.company_id, owner_id=bound.actor_id, paused=True)
    now = m.now
    allrows: list[Any] = [
        control,
        DirectoryCompany(
            company_id=bound.company_id,
            workspace_id=bound.workspace_id,
            owner_id=bound.actor_id,
            company_active=True,
            workspace_active=True,
        ),
        DirectoryMembership(
            company_id=bound.company_id,
            principal_id=bound.actor_id,
            role="owner",
            principal_active=True,
            membership_active=True,
        ),
    ]
    item = WorkItem(
        company_id=bound.company_id,
        task_id=rootdef.binding.task_id,
        trace_id=rootdef.binding.trace_id,
        goal_id=rootdef.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        acceptance=("management.non-executing-allocation.v1",),
        budget_usd=rootdef.allocation_usd,
    )
    rootwork = execution(rootdef.binding, item, rootdef.quota, None, 0)
    rootwork.plan_revisions_used = 1
    for kind in KINDS:
        setattr(
            rootwork,
            kind + "_delegated",
            sum(getattr(s.child.quota, kind) for s in admission.slots),
        )
    works = [rootwork] + [
        execution(
            s.child.binding,
            s.work,
            s.child.quota,
            rootdef.binding.task_id,
            3 if s.role == "sender" else 2 if s.role in {"strategy", "strategy_check"} else 0,
        )
        for s in admission.slots
    ]
    for w, s in zip(works[1:], admission.slots, strict=True):
        w.tool_attempts_used = int(s.role in {"strategy", "strategy_check", "sender"})
        w.state = "outcome_unknown" if s.role == "sender" else "eligible"
    work = works[-1]
    allrows += works
    directories = []
    for w in works:
        quota = (
            registration(rootdef.binding, item, rootdef.quota).work.budget_usd
            if w is rootwork
            else next(
                s.child.allocation_usd
                for s in admission.slots
                if s.child.binding.task_id == w.task_id
            )
        )
        directories.append(
            RegisteredWork(
                company_id=bound.company_id,
                workspace_id=w.workspace_id,
                task_id=w.task_id,
                trace_id=w.trace_id,
                actor_id=w.actor_id,
                parent_task_id=w.parent_task_id,
                root_task_id=rootdef.binding.task_id,
                allocation_usd=quota,
                delegated_usd=sum((s.child.allocation_usd for s in admission.slots), Decimal(0))
                if w is rootwork
                else Decimal(0),
                active=False,
            )
        )
    allrows += directories
    allrows.append(
        WorkPrincipal(
            company_id=bound.company_id, task_id=bound.task_id, principal_id=bound.actor_id
        )
    )
    stored: dict[tuple[type[object], object], object] = {}
    key: object
    for row in allrows:
        if isinstance(row, DirectoryCompany):
            key = bound.company_id
        elif isinstance(row, DirectoryMembership):
            key = (bound.company_id, bound.actor_id)
        elif isinstance(row, WorkPrincipal):
            key = (bound.company_id, bound.task_id, bound.actor_id)
        else:
            key = (bound.company_id, row.task_id) if hasattr(row, "task_id") else bound.company_id
        stored[(type(row), key)] = row
    for revision, payload in (
        (1, data.proof.original.prepared.original.snapshot.scope.producing_plan),
        (2, m.guard.registration.plan),
    ):
        body = data.proof.initial.pair.plan if revision == 2 else declared(admission, 1)
        if revision == 2:
            body = data.payload
        # Reuse the same typed fixture; every original layout/hash remains exact.
        assert canonical_sha256(body) == payload.sha256
        r = ManagementPlanRevision(
            company_id=bound.company_id,
            plan_id=payload.plan_id,
            plan_revision_id=payload.plan_revision_id,
            revision=revision,
            goal_id=admission.goal.goal_id,
            goal_revision_id=admission.goal.revision_id,
            mandate_revision_id=admission.mandate.revision_id,
            sha256=payload.sha256,
            snapshot_json=body.model_dump_json(),
            proposed_by=bound.actor_id,
            recorded_at=now - timedelta(seconds=6 - revision),
        )
        d = ManagementOwnerDecision(
            company_id=bound.company_id,
            decision_id=UUID(int=1800 + revision),
            plan_revision_id=r.plan_revision_id,
            owner_id=bound.actor_id,
            kind="approve",
            payload_sha256=r.sha256,
            reason="Recorded history fixture only",
            recorded_at=now - timedelta(seconds=5 - revision),
        )
        allrows += [r, d]
        stored[(ManagementPlanRevision, (bound.company_id, r.plan_revision_id))] = r
        stored[(ManagementOwnerDecision, (bound.company_id, d.decision_id))] = d
    procedure = ManagementProcedure(
        company_id=bound.company_id,
        procedure_id=rootdef.procedure_id,
        goal_id=rootdef.goal_id,
        parent_task_id=rootdef.binding.task_id,
        parent_run_id=rootdef.binding.run_id,
        allocation_usd=rootdef.allocation_usd,
        binding_json=rootdef.binding.model_dump_json(),
        quota_json=rootdef.quota.model_dump_json(),
        recorded_at=now - timedelta(seconds=5),
    )
    allrows.append(procedure)
    stored[(ManagementProcedure, (bound.company_id, rootdef.procedure_id))] = procedure
    for slot, w in zip(admission.slots, works[1:], strict=True):
        child = slot.child
        native_row = ManagementPlanTask(
            company_id=bound.company_id,
            plan_revision_id=m.guard.registration.plan.plan_revision_id,
            task_id=w.task_id,
            run_id=w.run_id,
            goal_id=rootdef.goal_id,
            procedure_id=rootdef.procedure_id,
            department_id=child.charter.department_id,
            charter_revision_id=child.charter.revision_id,
            allocation_usd=child.allocation_usd,
            quota_json=child.quota.model_dump_json(),
            binding_json=child.binding.model_dump_json(),
            work_sha256=w.registration_hash,
        )
        allrows.append(native_row)
        if slot.verification is not None:
            edge = slot.verification
            allrows.append(
                ManagementVerificationBinding(
                    company_id=bound.company_id,
                    plan_revision_id=native_row.plan_revision_id,
                    author_task_id=edge.author_task_id,
                    verifier_task_id=edge.verifier_task_id,
                    check_recipe=edge.check_recipe,
                )
            )
    event = ManagementRevisionEvent(
        company_id=bound.company_id,
        event_id=UUID(int=1899),
        procedure_id=rootdef.procedure_id,
        parent_task_id=rootdef.binding.task_id,
        parent_run_id=rootdef.binding.run_id,
        previous_plan_revision_id=data.proof.original.prepared.original.snapshot.scope.producing_plan.plan_revision_id,
        next_plan_revision_id=m.guard.registration.plan.plan_revision_id,
        owner_decision_id=UUID(int=1802),
        owner_id=bound.actor_id,
        revision_counter=1,
        recorded_at=now - timedelta(seconds=3),
    )
    allrows.append(event)
    command = SegmentCommand(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        action_id=m.action_id,
        segment_id=m.lease.segment_id,
    )
    allrows.append(
        SegmentDispatch(
            company_id=bound.company_id,
            action_id=m.action_id,
            task_id=bound.task_id,
            run_id=bound.run_id,
            segment_id=command.segment_id,
            workflow_id=command.workflow_id,
            binding_json=command.model_dump_json(),
        )
    )
    params = NotificationDispatchParameters(
        draft_id=m.draft_id, payload_sha256="a" * 64, recipient_policy_sha256="b" * 64
    )
    action = ActionProposal(
        company_id=bound.company_id,
        action_id=m.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool=NOTIFICATION_TOOL,
        tool_version="v1",
        resource=m.check.resource_symbol,
        parameters=params.model_dump(mode="json"),
        policy_version="p1",
        price_version="p1",
        estimated_cost_usd=Decimal(".01"),
    )
    row = JournalAction(
        id=m.action_id,
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_json=action.model_dump_json(),
        proposal_hash=action_hash(action),
        state="authorized",
        consumed_at=now - timedelta(seconds=2),
    )
    intent = EffectIntent(
        company_id=bound.company_id,
        action_id=m.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        run_id=bound.run_id,
        proposal_hash=action_hash(action),
        intent_fence=1,
        attempt_kind="tool_attempts",
        state="outcome_unknown",
        created_at=now - timedelta(seconds=1),
    )
    attempt = ExecutionAttempt(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        attempt_id=m.action_id,
        kind="tool_attempts",
        fence=1,
        reserved_at=intent.created_at,
    )
    dispatch_slot = NotificationDispatchRow(
        company_id=bound.company_id,
        draft_id=m.draft_id,
        action_id=m.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        run_id=bound.run_id,
        intent_fence=1,
        attempt_kind="tool_attempts",
        proposal_sha256=action_hash(action),
        registration_sha256=work.registration_hash,
        payload_sha256=params.payload_sha256,
        recipient_policy_sha256=params.recipient_policy_sha256,
        idempotency_key=stable_idempotency_key(bound.company_id, m.draft_id),
        kind="routine",
        bangkok_day=intent.created_at.astimezone(ZoneInfo("Asia/Bangkok")).date(),
        issued_at=intent.created_at,
        issued_by=bound.actor_id,
        operation_id=m.action_id,
        audit_trace_id=bound.trace_id,
    )
    for value, key in (
        (row, m.action_id),
        (intent, (bound.company_id, m.action_id)),
        (attempt, (bound.company_id, bound.task_id, m.action_id)),
        (dispatch_slot, (bound.company_id, m.draft_id)),
    ):
        allrows.append(value)
        stored[(type(value), key)] = value
    case = HistoryCase(m, control, work, command, allrows, stored, now)
    case.session = Queries(cast(Stage, case)).session
    return case
