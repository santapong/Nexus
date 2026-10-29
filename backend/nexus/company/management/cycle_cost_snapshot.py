"""Owner financial audit of the actual complete registered family, not a selected-work report.

Cohesion exception: complete family projection and one native/source final CC
window exceed400 lines; this is a closed financial read, not a report framework.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_cost_contracts import (
    MAX_CHARGES,
    MAX_FAMILY_ROWS,
    SNAPSHOT_LIMIT,
    CycleCostRead,
    CycleCostSnapshot,
    FamilyCharge,
    FamilyCostCapture,
    ModelCostRead,
    NativeBudgetSignature,
    NativeCostSelection,
    family_capture_signature,
    family_charge_totals,
)
from nexus.company.management.cycle_model_reader import (
    CycleModelReader,
    cost_read_end,
    directory_cost_work,
    native_cost_selection,
    native_hold,
    stored_coding_profile,
)
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.nexus_coding_catalog import coding_work_matches_template
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_models import ManagementProcedure
from nexus.company.management.plan_registration import registration
from nexus.company.management.planning_native_facts import require_time
from nexus.company.management.plans import RunBinding
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.effect_support import effect_record
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction, WorkBudget


def _charge(selected: NativeCostSelection, model: ModelCostRead | None) -> FamilyCharge:
    action, intent, hold = selected.action.proposal, selected.intent, selected.hold
    kind = (
        intent.attempt_kind
        if intent
        else ("model_requests" if action.tool == "model.request.v1" else "tool_attempts")
    )
    blockers = []
    receipt = intent.receipt if intent else None
    if intent is not None:
        work = selected.directory.work
        if work is None or (
            intent.company_id,
            intent.task_id,
            intent.trace_id,
            intent.run_id,
            intent.proposal_hash,
        ) != (
            action.company_id,
            action.task_id,
            action.trace_id,
            work.registration.run_id if work else None,
            selected.action.proposal_hash,
        ):
            blockers.append("native_intent_mismatch")
        attempt = selected.attempt
        if attempt is None or (
            attempt.company_id,
            attempt.task_id,
            attempt.trace_id,
            attempt.attempt_id,
            attempt.kind,
            attempt.fence,
            attempt.reserved_at,
        ) != (
            action.company_id,
            action.task_id,
            action.trace_id,
            action.action_id,
            intent.attempt_kind,
            intent.intent_fence,
            intent.created_at,
        ):
            blockers.append("native_attempt_mismatch")
        if hold is None:
            blockers.append("issued_hold_missing")
        elif hold.day != billing_day(intent.created_at):
            # Native begin transfers only an unissued hold to this intent day;
            # later SDK/receipt clocks do not move an issued/unknown charge.
            blockers.append("native_day_mismatch")
        if receipt is None:
            blockers.append("native_receipt_missing")
        elif (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
            receipt.outcome,
        ) != (
            action.company_id,
            action.action_id,
            action.task_id,
            action.trace_id,
            selected.action.proposal_hash,
            intent.state,
        ):
            blockers.append("native_receipt_mismatch")
        if (
            intent.state not in {"succeeded", "failed"}
            or hold is None
            or hold.state != "reconciled"
            or hold.actual_usd is None
        ):
            blockers.append("native_charge_unconfirmed")
        if kind == "model_requests":
            if model is None or model.fact is None:
                blockers.extend(model.blockers if model else ("source_proof_unavailable",))
            elif model.fact.billing != "known":
                blockers.extend(model.fact.blockers)
    elif hold is not None and hold.actual_usd is not None:
        blockers.append("reconciled_without_native_intent")
    return FamilyCharge(
        action_id=action.action_id,
        task_id=action.task_id,
        attempt_kind=kind,
        native_state=intent.state if intent else None,
        hold_state=hold.state if hold else None,
        reserved_usd=hold.amount_usd if hold else None,
        ledger_actual_usd=hold.actual_usd if hold else None,
        receipt_id=receipt.receipt_id if receipt else None,
        day=hold.day if hold else None,
        confirmation="unconfirmed" if blockers else "unissued" if intent is None else "known",
        blockers=tuple(dict.fromkeys(blockers)),
        model_fact=model.fact if model else None,
    )


def project_family_costs(
    admission: NexusCodingAdmission, captured: FamilyCostCapture, models: dict[UUID, ModelCostRead]
) -> CycleCostSnapshot:
    """Pure projection of actual captured data; public reader owns every authority check."""
    expected = {
        admission.procedure.binding.task_id,
        *(slot.work.task_id for slot in admission.slots),
    }
    observed = {row.task_id for row in captured.works}
    slots = {slot.work.task_id: slot for slot in admission.slots}
    mismatched = set()
    for row in captured.works:
        slot = slots.get(row.task_id)
        if row.work is None:
            mismatched.add(row.task_id)
        elif row.task_id == admission.procedure.binding.task_id:
            root = admission.procedure
            item = WorkItem(
                company_id=admission.company_id,
                task_id=root.binding.task_id,
                trace_id=root.binding.trace_id,
                goal_id=admission.goal.goal_id,
                department="management",
                title="Non-executing goal procedure allocation",
                acceptance=("management.non-executing-allocation.v1",),
                budget_usd=root.allocation_usd,
            )
            if (
                row.parent_task_id,
                row.root_task_id,
                row.actor_id,
                row.workspace_id,
                row.allocation_usd,
            ) != (
                None,
                root.binding.task_id,
                root.binding.actor_id,
                root.binding.workspace_id,
                root.allocation_usd,
            ) or row.work.registration != registration(root.binding, item, root.quota):
                mismatched.add(row.task_id)
        elif slot is not None and (
            row.parent_task_id != admission.procedure.binding.task_id
            or row.root_task_id != admission.procedure.binding.task_id
            or (
                row.work.registration.work != slot.work
                if slot.role == "planner"
                else not coding_work_matches_template(row.work.registration.work, slot.work)
            )
            or row.work.registration
            != registration(slot.child.binding, row.work.registration.work, slot.child.quota)
            or (row.actor_id, row.workspace_id, row.allocation_usd)
            != (
                slot.child.binding.actor_id,
                slot.child.binding.workspace_id,
                slot.child.allocation_usd,
            )
        ):
            mismatched.add(row.task_id)
    complete = captured.profile_bound and expected == observed and not mismatched
    charges = [
        _charge(row, models.get(row.action.proposal.action_id)) for row in captured.selections
    ]
    known = {row.action_id for row in charges}
    orphan_intents = {row.action_id: row for row in captured.orphan_effects}
    for hold in captured.orphan_holds:
        effect = orphan_intents.pop(hold.action_id, None)
        if hold.action_id in known:
            raise ValueError("Duplicate orphan native charge")
        charges.append(
            FamilyCharge(
                action_id=hold.action_id,
                task_id=hold.task_id,
                attempt_kind=effect.attempt_kind if effect else "unknown",
                native_state=effect.state if effect else None,
                hold_state=hold.state,
                reserved_usd=hold.amount_usd,
                ledger_actual_usd=hold.actual_usd,
                day=hold.day,
                receipt_id=effect.receipt.receipt_id if effect and effect.receipt else None,
                confirmation="unconfirmed",
                blockers=("native_action_missing",),
            )
        )
    for effect in orphan_intents.values():
        charges.append(
            FamilyCharge(
                action_id=effect.action_id,
                task_id=effect.task_id,
                attempt_kind=effect.attempt_kind,
                native_state=effect.state,
                hold_state=None,
                reserved_usd=None,
                ledger_actual_usd=None,
                receipt_id=None,
                confirmation="unconfirmed",
                blockers=("issued_hold_missing", "native_action_missing"),
            )
        )
    issued = {row.directory.task_id for row in captured.selections if row.intent is not None}
    issued.update(row.task_id for row in captured.orphan_effects)
    blockers = list(captured.blockers)
    if not captured.profile_bound:
        blockers.append("stored_full_profile_unavailable")
    if expected - observed:
        blockers.append("registered_family_incomplete")
    if observed - expected or mismatched:
        blockers.append("registered_family_differs")
    charge_rows = tuple(sorted(charges, key=lambda row: row.action_id))
    totals = family_charge_totals(charge_rows)
    if not complete or blockers:
        totals = totals.model_copy(update={"actual_total_usd": None})
    return CycleCostSnapshot(
        company_id=admission.company_id,
        goal=admission.goal,
        root_task_id=admission.procedure.binding.task_id,
        procedure_id=admission.procedure.procedure_id,
        admission_sha256=canonical_sha256(admission),
        observed_at=captured.observed_at,
        profile_bound=captured.profile_bound,
        complete_membership=complete,
        expected_task_ids=tuple(sorted(expected)),
        observed_task_ids=tuple(sorted(observed)),
        missing_task_ids=tuple(sorted(expected - observed)),
        extra_task_ids=tuple(sorted(observed - expected)),
        mismatched_task_ids=tuple(sorted(mismatched)),
        unissued_task_ids=tuple(sorted(expected - issued)),
        charges=charge_rows,
        totals=totals,
        blockers=tuple(dict.fromkeys(blockers)),
    )


class CycleCostSnapshotReader:
    """One concrete original graph; native capture and final recheck bracket actual private IO."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        models: CycleModelReader,
    ) -> None:
        if (
            type(models) is not CycleModelReader
            or models.factory is not factory
            or models.catalog is not catalog
        ):
            raise ValueError("Family financial snapshot requires the same concrete graph")
        self.factory, self.catalog, self.models = factory, catalog, models
        self._bound = (factory, catalog, models)
        self.require_composition()

    def require_composition(self) -> None:
        if any(
            a is not b
            for a, b in zip((self.factory, self.catalog, self.models), self._bound, strict=True)
        ):
            raise ManagementDeniedError("Original family financial graph changed")
        self.models.require_composition()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return self.models.pending_owners()

    async def _capture(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end: int
    ) -> FamilyCostCapture:
        # Cohesion exception: the bounded actual root, complete registrations and
        # all native leaf financial rows must be captured under one company mutex.
        self.require_composition()
        async with management_owner_transaction(
            self.factory, scope, owner.identity, allow_paused=True
        ) as (session, control, _):
            return await self._capture_locked(session, control, scope, owner, end)

    async def _capture_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        end: int,
    ) -> FamilyCostCapture:
        """Cohesion exception: all bounded family/native/budget rows share one CC snapshot."""
        self.require_composition()
        admission = self.models.admission
        root = admission.procedure.binding
        self.models._owner(scope, owner, control, end)
        procedure = await session.get(
            ManagementProcedure, (scope.company_id, admission.procedure.procedure_id)
        )
        if procedure is None or (
            procedure.goal_id,
            procedure.parent_task_id,
            procedure.parent_run_id,
            procedure.allocation_usd,
            RunBinding.model_validate_json(procedure.binding_json),
            AttemptQuota.model_validate_json(procedure.quota_json),
        ) != (
            admission.goal.goal_id,
            root.task_id,
            root.run_id,
            admission.procedure.allocation_usd,
            root,
            admission.procedure.quota,
        ):
            raise ManagementDeniedError(
                "Actual native family root differs from configured procedure"
            )
        directories = tuple(
            (
                await session.scalars(
                    select(RegisteredWork)
                    .where(
                        RegisteredWork.company_id == scope.company_id,
                        RegisteredWork.root_task_id == root.task_id,
                    )
                    .order_by(RegisteredWork.task_id)
                    .limit(MAX_FAMILY_ROWS + 1)
                )
            ).all()
        )
        if len(directories) > MAX_FAMILY_ROWS or not any(
            row.task_id == root.task_id for row in directories
        ):
            raise ManagementDeniedError("Actual native family root is absent or exceeds its bound")
        ids = {row.task_id for row in directories} | {slot.work.task_id for slot in admission.slots}
        works = []
        for row in directories:
            raw = await session.get(ExecutionWork, (scope.company_id, row.task_id))
            works.append(directory_cost_work(row, raw))
        actions = tuple(
            (
                await session.scalars(
                    select(JournalAction)
                    .where(
                        JournalAction.company_id == scope.company_id,
                        JournalAction.task_id.in_(ids),
                    )
                    .order_by(JournalAction.id)
                    .limit(MAX_CHARGES + 1)
                )
            ).all()
        )
        holds = tuple(
            (
                await session.scalars(
                    select(CostHold)
                    .where(
                        CostHold.company_id == scope.company_id,
                        CostHold.task_id.in_(ids),
                    )
                    .order_by(CostHold.action_id)
                    .limit(MAX_CHARGES + 1)
                )
            ).all()
        )
        effects = tuple(
            (
                await session.scalars(
                    select(EffectIntent)
                    .where(
                        EffectIntent.company_id == scope.company_id,
                        EffectIntent.task_id.in_(ids),
                    )
                    .order_by(EffectIntent.action_id)
                    .limit(MAX_CHARGES + 1)
                )
            ).all()
        )
        if max(len(actions), len(holds), len(effects)) > MAX_CHARGES:
            raise ManagementDeniedError("Family native financial row bound exceeded")
        selections = tuple(
            [await native_cost_selection(session, scope.company_id, row.id) for row in actions]
        )
        action_ids = {row.id for row in actions}
        profile = await stored_coding_profile(
            session,
            admission,
            works=tuple(
                row.work.registration.work
                for row in works
                if row.work is not None
                and row.task_id not in {root.task_id, admission.slots[0].work.task_id}
            ),
        )
        blockers = []
        budgets = []
        for task in ids:
            budget = await session.get(WorkBudget, (scope.company_id, task))
            budgets.append(
                (
                    task,
                    budget.spent_usd if budget else None,
                    budget.held_usd if budget else None,
                )
            )
            spent = sum(
                (
                    row.actual_usd or Decimal(0)
                    for row in holds
                    if row.task_id == task and row.state == "reconciled"
                ),
                Decimal(0),
            )
            held = sum(
                (
                    row.amount_usd
                    for row in holds
                    if row.task_id == task and row.state in {"held", "unknown"}
                ),
                Decimal(0),
            )
            if (budget is None and (spent or held)) or (
                budget is not None and (budget.spent_usd, budget.held_usd) != (spent, held)
            ):
                blockers.append("native_budget_mismatch")
        observed = await db_now(session)
        self.models._owner(scope, owner, control, end)
        return FamilyCostCapture(
            observed_at=observed,
            owner_id=control.owner_id,
            control_policy=control.policy_version,
            control_prices=control.price_version,
            control_paused=control.paused,
            profile_bound=profile,
            works=tuple(works),
            selections=selections,
            orphan_holds=tuple(
                native_hold(row) for row in holds if row.action_id not in action_ids
            ),
            orphan_effects=tuple(
                effect_record(row) for row in effects if row.action_id not in action_ids
            ),
            native_budget_sha256=canonical_sha256(
                NativeBudgetSignature(values=tuple(sorted(budgets)))
            ),
            blockers=tuple(dict.fromkeys(blockers)),
        )

    async def read(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, *, end_us: int
    ) -> CycleCostRead:
        self.require_composition()
        end = cost_read_end(scope, owner, end_us)
        first = await self.models.owned(self._capture(scope, owner, end), end)
        signature = family_capture_signature(first)
        model_facts = {}
        for selected in first.selections:
            if selected.intent is not None and selected.action.proposal.tool == "model.request.v1":
                found = await self.models.read(
                    scope, owner, selected.action.proposal.action_id, end_us=end
                )
                end = min(end, found.read_end_us)
                model_facts[selected.action.proposal.action_id] = found
        return await self.models.owned(self._final(scope, owner, signature, model_facts, end), end)

    async def _final(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        signature: str,
        models: dict[UUID, ModelCostRead],
        end: int,
    ) -> CycleCostRead:
        async with management_owner_transaction(
            self.factory, scope, owner.identity, allow_paused=True
        ) as (session, control, _):
            final = await self._capture_locked(session, control, scope, owner, end)
            if family_capture_signature(final) != signature:
                raise ManagementDeniedError("Native financial family changed during protected read")
            checked = {}
            for key, result in models.items():
                result = await self.models.revalidate_locked(
                    session, control, scope, owner, result, end
                )
                end = min(end, result.read_end_us)
                checked[key] = result
            value = project_family_costs(self.models.admission, final, checked)
            raw = value.model_dump_json(by_alias=True).encode()
            if len(raw) > SNAPSHOT_LIMIT:
                raise ManagementDeniedError("Complete family financial snapshot exceeds its bound")
            value = CycleCostSnapshot.model_validate_json(raw)
            self.models._owner(scope, owner, control, end)
        self.require_composition()
        require_time(end)
        owner.require_time(datetime.now(UTC))
        return CycleCostRead(value, end)
