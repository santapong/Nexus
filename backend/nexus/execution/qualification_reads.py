"""Current-owner qualification reads; no call permission.

The DB-admission and two-transaction protected-result joins stay together so
current owner access is visibly checked on both sides of filesystem delivery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.control_support import current_mandate, validate_mandate
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.governance_models import ManagementGoalHead
from nexus.company.management.plan_models import ManagementProcedure
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.core.llm.company_pricing import CostQuote
from nexus.core.llm.qualification_contracts import (
    PROFILE,
    VERSION,
    WORKFLOW,
    QualificationRecipe,
    qualification_request,
    recipe_hash,
)
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.effect_support import effect_record
from nexus.execution.qualification_read_contracts import (
    QualificationDispatchRecord,
    QualificationEffectView,
    QualificationHoldView,
    QualificationRecipeView,
    QualificationResultView,
    QualificationStatus,
)
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.qualification_worker_recovery import (
    QualificationHoldFacts,
    require_saved_result,
)
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionSnapshot
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import next_segment_id
from nexus.execution.runtime_support import db_now, snapshot
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.harness.journal_submission import pending_action_record
from nexus.harness.qualification_evidence import (
    FileQualificationEvidenceStore,
    IssuedQualificationEvidence,
    current,
)


async def require_current_recipe_locked(
    preparation: QualificationPreparationService,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    recipe: QualificationRecipe,
) -> CostQuote:
    """Only DB reads and exact frozen recipe data under CompanyControl; no SDK/source IO."""
    if (identity.principal_id, scope.principal_id) != (control.owner_id, control.owner_id):
        raise ManagementDeniedError("Qualification requires its current signed owner")
    goal = await GoalStore._current(session, scope, recipe.goal)
    head = await session.get(ManagementGoalHead, (scope.company_id, recipe.goal.goal_id))
    if head is None or not head.active or goal.definition.owner_id != control.owner_id:
        raise ManagementDeniedError("Qualification current goal is unavailable")
    mandate = await current_mandate(session, scope, goal.definition.mandate)
    validate_mandate(mandate.mandate, control)
    if mandate.mandate.goals and recipe.goal.goal_id not in mandate.mandate.goals:
        raise ManagementDeniedError("Qualification goal is outside current mandate")
    if (
        await session.scalar(
            select(ManagementProcedure).where(
                ManagementProcedure.company_id == scope.company_id,
                ManagementProcedure.goal_id == recipe.goal.goal_id,
            )
        )
        is not None
    ):
        raise ManagementDeniedError("Qualification cannot replace a delivery goal root")
    quote = preparation._quote(recipe, control, await db_now(session))
    if preparation._allocation > min(
        control.work_cap_usd,
        control.daily_cap_usd,
        mandate.mandate.work_cap_usd,
        mandate.mandate.daily_cap_usd,
    ):
        raise ManagementDeniedError("Qualification allocation exceeds current limits")
    if quote.amount_usd > preparation._allocation or control.paused:
        raise ManagementDeniedError("Qualification current quote or intake is unavailable")
    return quote


def require_qualification_work(
    preparation: QualificationPreparationService,
    work: ExecutionWork,
    recipe: QualificationRecipe,
) -> ExecutionSnapshot:
    """Exact immutable registration for history too; this does not require live eligibility."""
    saved = snapshot(work)
    registration = saved.registration
    if (
        (work.workflow_name, work.workflow_version, work.model_profile, work.model_registry_version)
        != (WORKFLOW, VERSION, PROFILE, recipe.registry_revision)
        or registration.work.goal_id != recipe.goal.goal_id
        or saved.parent_task_id is not None
        or registration.work.budget_usd != preparation._allocation
        or registration.work.acceptance
        != (recipe.purpose, "target-set:" + preparation._target_set(recipe))
        or registration.quota
        != AttemptQuota(model_requests=12, tool_attempts=0, rework_rounds=0, plan_revisions=0)
    ):
        raise ManagementDeniedError("Qualification actual work differs from frozen catalog")
    return saved


async def qualification_rows(
    preparation: QualificationPreparationService,
    session: AsyncSession,
    scope: CompanyControlScope,
    action_id: UUID,
) -> tuple[JournalAction, ExecutionWork, ActionRecord, QualificationRecipe, SegmentCommand | None]:
    row = await session.get(JournalAction, action_id)
    if row is None or row.company_id != scope.company_id or row.id != action_id:
        raise ManagementDeniedError("Qualification action is unavailable")
    record = pending_action_record(row)
    work = await session.get(ExecutionWork, (scope.company_id, row.task_id))
    if work is None or work.company_id != scope.company_id or work.task_id != row.task_id:
        raise ManagementDeniedError("Qualification native work is unavailable")
    saved = snapshot(work)
    dispatch = await session.get(SegmentDispatch, (scope.company_id, action_id))
    command = (
        SegmentCommand.model_validate_json(dispatch.binding_json)
        if dispatch
        else SegmentCommand(
            company_id=work.company_id,
            task_id=work.task_id,
            trace_id=work.trace_id,
            actor_id=work.actor_id,
            workspace_id=work.workspace_id,
            run_id=work.run_id,
            action_id=row.id,
            segment_id=next_segment_id(saved),
        )
    )
    # The unissued descriptor above only selects a catalog recipe, never a lease/dispatch.
    if (
        command.company_id,
        command.task_id,
        command.trace_id,
        command.actor_id,
        command.workspace_id,
        command.run_id,
        command.action_id,
    ) != (
        work.company_id,
        work.task_id,
        work.trace_id,
        work.actor_id,
        work.workspace_id,
        work.run_id,
        row.id,
    ):
        raise ManagementDeniedError("Qualification dispatch/work binding differs")
    if dispatch and (
        dispatch.task_id,
        dispatch.run_id,
        dispatch.segment_id,
        dispatch.workflow_id,
        dispatch.binding_json,
    ) != (
        command.task_id,
        command.run_id,
        command.segment_id,
        command.workflow_id,
        command.model_dump_json(),
    ):
        raise ManagementDeniedError("Qualification stored dispatch is inconsistent")
    recipe = preparation.recipe_for_action(command, record)
    require_qualification_work(preparation, work, recipe)
    return row, work, record, recipe, command if dispatch else None


@dataclass(frozen=True, slots=True)
class QualificationReader:
    preparation: QualificationPreparationService
    evidence: FileQualificationEvidenceStore | None = None

    @property
    def factory(self) -> async_sessionmaker[AsyncSession]:
        return self.preparation.factory

    async def _view(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        recipe: QualificationRecipe,
    ) -> QualificationRecipeView:
        try:
            quote = await require_current_recipe_locked(
                self.preparation, session, control, scope, identity, recipe
            )
        except ValueError:
            quote = None
        return QualificationRecipeView(
            recipe_id=recipe.recipe_id,
            recipe_sha256=recipe_hash(recipe),
            revision=recipe.revision,
            case_id=recipe.case_id,
            goal=recipe.goal,
            provider=recipe.target.provider,
            model_id=recipe.target.model_id,
            input_text=recipe.input_text,
            system_text=recipe.system_text,
            output_schema=recipe.output_schema,
            request_output_cap=recipe.request_output_cap,
            maximum_reservation=quote,
            availability="current" if quote is not None else "unavailable",
            expires_at=recipe.valid_until,
        )

    async def recipes(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
    ) -> tuple[QualificationRecipeView, ...]:
        views = []
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            for recipe in self.preparation.configured_recipes():
                if recipe.goal.company_id != scope.company_id:
                    continue
                views.append(await self._view(session, control, scope, identity, recipe))
            final = await db_now(session)
            for index, view in enumerate(views):
                if view.maximum_reservation is not None and final >= view.expires_at:
                    views[index] = view.model_copy(
                        update={"availability": "unavailable", "maximum_reservation": None}
                    )
        return tuple(views)

    async def action_status(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
    ) -> QualificationStatus:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            row, work, record, recipe, command = await qualification_rows(
                self.preparation, session, scope, action_id
            )
            held = await session.get(CostHold, row.id)
            effect = await session.get(EffectIntent, (scope.company_id, row.id))
            native = effect_record(effect) if effect else None
            view = await self._view(session, control, scope, identity, recipe)
            return QualificationStatus(
                observed_at=await db_now(session),
                action=record,
                work=snapshot(work),
                recipe=view,
                hold=QualificationHoldView(
                    state=cast(Literal["held", "unknown", "reconciled"], held.state),
                    amount_usd=held.amount_usd,
                    actual_usd=held.actual_usd,
                    day=held.day,
                )
                if held
                else None,
                effect=QualificationEffectView(
                    action_id=effect.action_id,
                    state=effect.state,
                    intent_fence=effect.intent_fence,
                    created_at=effect.created_at,
                    evidence_sha256s=tuple(ref.sha256 for ref in native.receipt.artifacts)
                    if native is not None and native.receipt is not None
                    else (),
                )
                if effect
                else None,
                dispatch=QualificationDispatchRecord(
                    command=command, workflow_id=command.workflow_id, disposition="existing"
                )
                if command
                else None,
            )

    async def result(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> QualificationResultView:
        """Read original protected terminal facts with current owner access before and after FS."""
        current(end_us)
        end_us = min(end_us, clock_us() + 30_000_000)
        store = self.evidence
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, _, _):
            row, work, record, recipe, _ = await qualification_rows(
                self.preparation, session, scope, action_id
            )
            raw = await session.get(EffectIntent, (scope.company_id, row.id))
            held = await session.get(CostHold, row.id)
            native = effect_record(raw) if raw else None
            unavailable = QualificationResultView(
                availability="unavailable", native_outcome=native.state if native else None
            )
            if (
                native is None
                or native.receipt is None
                or held is None
                or type(store) is not FileQualificationEvidenceStore
                or native.state not in {"succeeded", "failed", "outcome_unknown"}
                or len(native.receipt.artifacts) != 1
            ):
                return unavailable
            reference = native.receipt.artifacts[0]
            if (
                native.company_id,
                native.task_id,
                native.trace_id,
                native.run_id,
                native.action_id,
            ) != (work.company_id, work.task_id, work.trace_id, work.run_id, row.id) or (
                held.company_id,
                held.task_id,
                held.action_id,
            ) != (work.company_id, work.task_id, row.id):
                return unavailable
            if (
                reference.company_id != scope.company_id
                or identity.principal_id not in reference.allowed_principals
            ):
                return unavailable
            hold = QualificationHoldFacts(
                company_id=held.company_id,
                task_id=held.task_id,
                action_id=held.action_id,
                day=held.day,
                amount_usd=held.amount_usd,
                actual_usd=held.actual_usd,
                state=cast(Literal["held", "unknown", "reconciled"], held.state),
            )
            request = qualification_request(
                recipe,
                LedgerScope(
                    company_id=work.company_id,
                    principal_id=work.actor_id,
                    task_id=work.task_id,
                    trace_id=work.trace_id,
                ),
                action_id=row.id,
                request_id=uuid5(work.task_id, f"qualification-request:v1:{recipe_hash(recipe)}"),
            )
            pinned = (record.proposal_hash, native.model_dump_json(by_alias=True), hold)
        try:
            current(end_us)
            assert store is not None
            loaded = await store.load(reference, end_us=end_us)
            found = IssuedQualificationEvidence(reference, loaded)
            saved = require_saved_result(recipe, request, native, found, hold)
            current(end_us)
        except (ValueError, OSError, TimeoutError):
            return unavailable
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, _, _):
            row, _, record, actual_recipe, _ = await qualification_rows(
                self.preparation, session, scope, action_id
            )
            raw = await session.get(EffectIntent, (scope.company_id, row.id))
            held = await session.get(CostHold, row.id)
            if raw is None or held is None:
                return unavailable
            actual = effect_record(raw)
            final_hold = QualificationHoldFacts(
                company_id=held.company_id,
                task_id=held.task_id,
                action_id=held.action_id,
                day=held.day,
                amount_usd=held.amount_usd,
                actual_usd=held.actual_usd,
                state=cast(Literal["held", "unknown", "reconciled"], held.state),
            )
            if (
                actual_recipe != recipe
                or (record.proposal_hash, actual.model_dump_json(by_alias=True), final_hold)
                != pinned
            ):
                return unavailable
            if (
                actual.receipt is None
                or len(actual.receipt.artifacts) != 1
                or identity.principal_id not in actual.receipt.artifacts[0].allowed_principals
            ):
                return unavailable
            current(end_us)
            result = QualificationResultView(
                availability="available",
                provider_result=saved.provider_result,
                native_outcome=actual.state,
                captured_at=loaded.checked_at,
                sha256=reference.sha256,
                actual_usd=saved.actual_usd,
            )
        current(end_us)
        return result
