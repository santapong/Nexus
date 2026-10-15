"""Recorded full-family sender provenance; current facts here cannot authorize a fresh effect."""

# Slightly over400 lines keeps the fixed twelve-row partition and issuance chronology
# together under the approved three-module foundation; no general history framework.

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_admission import validate_stockflow_cycle
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanRevision,
    ManagementPlanTask,
    ManagementProcedure,
    ManagementRevisionEvent,
    ManagementVerificationBinding,
)
from nexus.company.management.plan_registration import registration, require_native_task
from nexus.company.management.plans import RunBinding
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.execution.cycle_partition_support import _execution, _same
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_dispatch_read import (
    require_issued_binding,
    require_notification_command,
)
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import KINDS, db_now, require_runtime_scope
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction


async def _rows[Row](session: AsyncSession, statement: Select[tuple[Row]]) -> tuple[Row, ...]:
    return tuple((await session.scalars(statement)).all())


def _require(value: bool) -> None:
    if not value:
        raise ExecutionDeniedError("Recorded mixed sender family is unavailable")


async def _recorded_plan(
    session: AsyncSession,
    control: CompanyControl,
    guard: NotificationOperationGuard,
    catalog: PlanAdmissionCatalog,
    admission: StockFlowCycleAdmission,
    intent_created_at: datetime,
) -> PlanRevision:
    reference = guard.registration.plan
    row = await session.get(
        ManagementPlanRevision, (control.company_id, reference.plan_revision_id)
    )
    _require(row is not None)
    assert row is not None
    record = plan_record(row)
    selected = validate_stockflow_cycle(admission, catalog.models, record.payload)
    _require(
        plan_reference(record) == reference
        and reference.revision == 2
        and selected is not None
        and selected.stage == "full"
        and record.payload.strategy_selection is not None
    )
    decisions = await _rows(
        session,
        select(ManagementOwnerDecision)
        .where(
            ManagementOwnerDecision.company_id == control.company_id,
            ManagementOwnerDecision.plan_revision_id == reference.plan_revision_id,
            ManagementOwnerDecision.kind == "approve",
        )
        .limit(2),
    )
    _require(len(decisions) == 1)
    decision = decisions[0]
    _require(
        _same(decision, "owner_id payload_sha256", (control.owner_id, record.sha256))
        and record.recorded_at <= decision.recorded_at <= intent_created_at
    )
    events = await _rows(
        session,
        select(ManagementRevisionEvent)
        .where(
            ManagementRevisionEvent.company_id == control.company_id,
            ManagementRevisionEvent.procedure_id == admission.procedure.procedure_id,
        )
        .limit(2),
    )
    _require(len(events) == 1)
    event = events[0]
    root = admission.procedure
    _require(
        _same(
            event,
            "procedure_id parent_task_id parent_run_id next_plan_revision_id "
            "owner_decision_id owner_id revision_counter",
            (
                root.procedure_id,
                root.binding.task_id,
                root.binding.run_id,
                record.plan_revision_id,
                decision.decision_id,
                control.owner_id,
                1,
            ),
        )
        and event.recorded_at == decision.recorded_at
    )
    previous = await session.get(
        ManagementPlanRevision, (control.company_id, event.previous_plan_revision_id)
    )
    _require(previous is not None)
    assert previous is not None
    old = plan_record(previous)
    first = validate_stockflow_cycle(admission, catalog.models, old.payload)
    _require(
        first is not None
        and first.stage == "strategy"
        and old.payload.procedure == record.payload.procedure
    )
    old_decisions = await _rows(
        session,
        select(ManagementOwnerDecision)
        .where(
            ManagementOwnerDecision.company_id == control.company_id,
            ManagementOwnerDecision.plan_revision_id == old.plan_revision_id,
            ManagementOwnerDecision.kind == "approve",
        )
        .limit(2),
    )
    _require(
        len(old_decisions) == 1
        and old_decisions[0].owner_id == control.owner_id
        and old_decisions[0].payload_sha256 == old.sha256
        and old.recorded_at <= old_decisions[0].recorded_at <= decision.recorded_at
    )
    return record


async def _family(
    session: AsyncSession, admission: StockFlowCycleAdmission, record: PlanRevision
) -> None:
    # Keep complete recorded twelve-row SQL identities and immutable partition comparisons cohesive.
    root = admission.procedure
    expected = {root.binding.task_id, *(s.child.binding.task_id for s in admission.slots)}
    directories = await _rows(
        session,
        select(RegisteredWork)
        .where(
            RegisteredWork.company_id == admission.company_id,
            RegisteredWork.root_task_id == root.binding.task_id,
        )
        .limit(1001)
        .with_for_update(),
    )
    works = await _rows(
        session,
        select(ExecutionWork)
        .where(
            ExecutionWork.company_id == admission.company_id,
            or_(ExecutionWork.task_id.in_(expected), ExecutionWork.parent_task_id.in_(expected)),
        )
        .limit(1001)
        .with_for_update(),
    )
    _require(
        len(directories) == len(works) == 12
        and {r.task_id for r in directories} == {r.task_id for r in works} == expected
    )
    directory = {r.task_id: r for r in directories}
    actual = {r.task_id: r for r in works}
    item = WorkItem(
        company_id=admission.company_id,
        task_id=root.binding.task_id,
        trace_id=root.binding.trace_id,
        goal_id=root.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        acceptance=("management.non-executing-allocation.v1",),
        budget_usd=root.allocation_usd,
    )
    parent = actual[root.binding.task_id]
    _execution(parent, registration(root.binding, item, root.quota))
    _require(
        (parent.actor_id, parent.workspace_id) == (root.binding.actor_id, root.binding.workspace_id)
    )
    _require(
        _same(
            parent,
            "parent_task_id state fence segment_number worker_id lease_until segment_id "
            "waiting_action_id lease_mode lease_principal_id",
            (None, "eligible", 0, 0, None, None, None, None, None, None),
        )
    )
    _require(tuple(getattr(parent, k + "_used") for k in KINDS) == (0, 0, 0, 1))
    _require(
        _same(
            directory[parent.task_id],
            "company_id workspace_id actor_id trace_id parent_task_id root_task_id "
            "allocation_usd delegated_usd",
            (
                admission.company_id,
                root.binding.workspace_id,
                root.binding.actor_id,
                root.binding.trace_id,
                None,
                parent.task_id,
                root.allocation_usd,
                sum((s.child.allocation_usd for s in admission.slots), Decimal(0)),
            ),
        )
    )
    natives = await _rows(
        session,
        select(ManagementPlanTask)
        .where(
            ManagementPlanTask.company_id == admission.company_id,
            ManagementPlanTask.plan_revision_id == record.plan_revision_id,
        )
        .limit(12),
    )
    _require(len(natives) == 11 and {r.task_id for r in natives} == expected - {parent.task_id})
    native = {r.task_id: r for r in natives}
    for slot in admission.slots:
        bound = slot.child.binding
        work = actual[bound.task_id]
        require_native_task(native[bound.task_id], work, slot.child, record.payload)
        _execution(work, registration(bound, slot.work, slot.child.quota))
        _require((work.actor_id, work.workspace_id) == (bound.actor_id, bound.workspace_id))
        _require(
            _same(
                directory[bound.task_id],
                "company_id workspace_id actor_id trace_id parent_task_id root_task_id "
                "allocation_usd delegated_usd",
                (
                    admission.company_id,
                    bound.workspace_id,
                    bound.actor_id,
                    bound.trace_id,
                    parent.task_id,
                    parent.task_id,
                    slot.child.allocation_usd,
                    Decimal(0),
                ),
            )
        )
        _require(
            work.parent_task_id == parent.task_id
            and all(getattr(work, k + "_delegated") == 0 for k in KINDS)
        )
        if slot.role in {"engineering", "engineering_check", "sender"}:
            _require(
                (work.model_requests_limit, work.model_requests_used, work.model_requests_delegated)
                == (0, 0, 0)
            )
    for kind in KINDS:
        _require(
            getattr(parent, kind + "_delegated")
            == sum(getattr(s.child.quota, kind) for s in admission.slots)
        )
    procedure = await session.get(ManagementProcedure, (admission.company_id, root.procedure_id))
    _require(procedure is not None)
    assert procedure is not None
    _require(
        _same(
            procedure,
            "goal_id parent_task_id parent_run_id allocation_usd",
            (root.goal_id, root.binding.task_id, root.binding.run_id, root.allocation_usd),
        )
        and RunBinding.model_validate_json(procedure.binding_json) == root.binding
        and AttemptQuota.model_validate_json(procedure.quota_json) == root.quota
    )
    edges = await _rows(
        session,
        select(ManagementVerificationBinding)
        .where(
            ManagementVerificationBinding.company_id == admission.company_id,
            ManagementVerificationBinding.plan_revision_id == record.plan_revision_id,
        )
        .limit(6),
    )
    expected_edges = {
        (r.author_task_id, r.verifier_task_id, r.check_recipe) for r in record.payload.verification
    }
    _require(
        len(edges) == len(expected_edges) == 5
        and {(r.author_task_id, r.verifier_task_id, r.check_recipe) for r in edges}
        == expected_edges
    )


async def require_recorded_cycle_sender_family_locked(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    guard: NotificationOperationGuard,
    command: SegmentCommand,
    catalog: PlanAdmissionCatalog,
) -> None:
    """Derive issuance from actual rows; no caller history flag or fresh source permission."""
    _require(session.in_transaction() and type(guard) is NotificationOperationGuard)
    admission = validate_cycle_catalog(catalog.cycle_admission, catalog)
    _require(admission is not None)
    assert admission is not None
    guard.require_identity(guard.witness.identity)
    guard.require_company(control.company_id)
    _require(
        canonical_sha256(catalog) == guard.registration.catalog_sha256
        and guard.registration.sender == admission.slots[-1].child.binding
        and control.owner_id == work.actor_id == guard.witness.identity.principal_id
    )
    _require(
        await session.scalar(
            select(CompanyControl)
            .where(CompanyControl.company_id == control.company_id)
            .with_for_update()
        )
        is control
    )
    _require(
        await session.scalar(
            select(ExecutionWork)
            .where(
                ExecutionWork.company_id == control.company_id,
                ExecutionWork.task_id == work.task_id,
            )
            .with_for_update()
        )
        is work
    )
    await require_strategy_application_role(session)
    scope = LedgerScope(
        company_id=work.company_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        principal_id=guard.witness.identity.principal_id,
    )
    command.require_scope(scope)
    registered = await require_runtime_scope(
        session, control, scope, guard.witness.identity, allow_inactive=True, owner_read=False
    )
    _require(
        registered.actor_id == work.actor_id
        and registered.workspace_id == guard.witness.identity.workspace_id
    )
    guard.require_time(await db_now(session))
    _require(await dispatched_binding(session, work, scope, command.segment_id) == command)
    row = await session.get(JournalAction, command.action_id)
    _require(
        row is not None
        and row.company_id == control.company_id
        and row.state == "authorized"
        and row.consumed_at is not None
    )
    assert row is not None and row.consumed_at is not None
    action = ActionProposal.model_validate_json(row.proposal_json)
    _require(row.proposal_hash == action_hash(action) and row.id == action.action_id)
    pins = require_notification_command(
        guard.registration.sender, action, command, admission.slots[-1].tool.resource
    )
    intent = await session.get(EffectIntent, (control.company_id, action.action_id))
    slot = await session.get(NotificationDispatchRow, (control.company_id, pins.draft_id))
    attempt = await session.get(
        ExecutionAttempt, (control.company_id, work.task_id, action.action_id)
    )
    _require(intent is not None and slot is not None and attempt is not None)
    assert intent is not None and slot is not None and attempt is not None
    require_issued_binding(work, action, pins, intent, slot)
    _require(
        intent.state in {"intent", "outcome_unknown", "succeeded", "failed"}
        and work.tool_attempts_used == 1
        and type(intent.intent_fence) is int
        and type(work.fence) is int
        and 0 < intent.intent_fence <= work.fence
    )
    _require(
        _same(
            attempt,
            "company_id task_id trace_id attempt_id kind fence",
            (
                work.company_id,
                work.task_id,
                work.trace_id,
                action.action_id,
                "tool_attempts",
                intent.intent_fence,
            ),
        )
        and row.consumed_at <= attempt.reserved_at <= intent.created_at
        and row.consumed_at <= slot.issued_at <= intent.created_at
    )
    record = await _recorded_plan(session, control, guard, catalog, admission, intent.created_at)
    await _family(session, admission, record)
    await require_runtime_scope(
        session, control, scope, guard.witness.identity, allow_inactive=True, owner_read=False
    )
    now = await db_now(session)
    _require(record.recorded_at <= intent.created_at <= now)
    guard.require_time(now)
