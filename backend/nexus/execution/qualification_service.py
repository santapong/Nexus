"""Owner preparation of bounded operational qualification work; never approval or execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid5

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_contracts import WorkRegistration
from nexus.company.directory_models import RegisteredWork
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import current_mandate, validate_mandate
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.governance_models import ManagementGoalHead
from nexus.company.management.plan_models import ManagementProcedure
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_pricing import CostQuote, ModelContract, quote_cost
from nexus.core.llm.qualification_contracts import (
    PROFILE,
    TOOL,
    WORKFLOW,
    QualificationRecipe,
    financial_bounds,
    qualification_parameters,
    qualification_request,
    recipe_hash,
    target_set_hash,
)
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration, ExecutionSnapshot
from nexus.execution.runtime_registration import register_locked
from nexus.execution.runtime_support import db_now, snapshot
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl
from nexus.harness.journal_submission import submit_pending_locked


class PreparedQualification(ModelContract):
    """Actual committed work/pending-action descriptions, not a lease, approval or permit."""

    work: ExecutionSnapshot
    action: ActionRecord
    request: CompanyModelRequest
    quote: CostQuote
    recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    company_completed: Literal[False] = False


@dataclass(frozen=True, slots=True, init=False)
class QualificationPreparationService:
    """Fixed server catalog/allocation, separate from delivery-plan roots and model eligibility."""

    factory: async_sessionmaker[AsyncSession]
    _recipes: tuple[QualificationRecipe, ...]
    _allocation: Decimal

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        recipes: tuple[QualificationRecipe, ...],
        *,
        allocation_usd: Decimal = Decimal("1.00"),
    ) -> None:
        if (
            factory is None
            or not isinstance(allocation_usd, Decimal)
            or not allocation_usd.is_finite()
            or not 0 < allocation_usd <= 5
            or allocation_usd != allocation_usd.quantize(Decimal("0.000001"))
            or not isinstance(recipes, tuple)
            or not 0 < len(recipes) <= 32
        ):
            raise ValueError("Qualification requires an exact fixed catalog and USD allocation")
        copied = tuple(
            QualificationRecipe.model_validate_json(value.model_dump_json(by_alias=True))
            for value in recipes
        )
        if len({value.recipe_id for value in copied}) != len(copied):
            raise ValueError("Qualification recipe IDs must be unique")
        goals = {(value.goal.company_id, value.goal.goal_id) for value in copied}
        if any(
            len(
                {
                    value.registry_revision
                    for value in copied
                    if (value.goal.company_id, value.goal.goal_id) == goal
                }
            )
            != 1
            for goal in goals
        ):
            raise ValueError("One qualification goal requires one frozen registry revision")
        for value in copied:
            targets = tuple(
                sorted(
                    {
                        canonical_sha256(candidate.target)
                        for candidate in copied
                        if (candidate.goal.company_id, candidate.goal.goal_id)
                        == (value.goal.company_id, value.goal.goal_id)
                    }
                )
            )
            if value.qualification_target_sha256s != targets:
                raise ValueError(
                    "Qualification declaration differs from complete server target set"
                )
        object.__setattr__(self, "factory", factory)
        object.__setattr__(self, "_recipes", copied)
        object.__setattr__(self, "_allocation", allocation_usd.quantize(Decimal("0.000001")))

    @staticmethod
    def _quote(recipe: QualificationRecipe, control: CompanyControl, now: datetime) -> CostQuote:
        if now.utcoffset() is None or now >= recipe.valid_until:
            raise ManagementDeniedError("Qualification recipe is no longer current")
        if recipe.target.price is None or control.price_version != recipe.target.price.version:
            raise ManagementDeniedError("Qualification recipe differs from actual company prices")
        return quote_cost(recipe.target.price, financial_bounds(recipe), now=now)

    def _target_set(self, recipe: QualificationRecipe) -> str:
        """One canonical complete target/config set survives all cases under this goal."""
        return target_set_hash(recipe.registry_revision, recipe.qualification_target_sha256s)

    async def prepare_qualification(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, recipe_id: str
    ) -> PreparedQualification:
        """Register one permanent goal-bound allowance and pending proposal atomically.

        No source/key/provider lookup, approval, hold, counter consumption, queue
        or external request occurs. Existing immutable directory/runtime/journal
        helpers reject changed identity/allocation/catalog instead of new roots.
        """
        scope = CompanyControlScope.model_validate_json(scope.model_dump_json())
        identity = VerifiedIdentity.model_validate_json(identity.model_dump_json())
        recipe = next((value for value in self._recipes if value.recipe_id == recipe_id), None)
        if recipe is None or recipe.goal.company_id != scope.company_id:
            raise ManagementDeniedError("Qualification recipe is unavailable for this company")
        if identity.principal_id != scope.principal_id:
            raise ManagementDeniedError("Qualification requires its actual signed owner")
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            goal = await GoalStore._current(session, scope, recipe.goal)
            head = await session.get(ManagementGoalHead, (scope.company_id, recipe.goal.goal_id))
            if (
                control.owner_id != identity.principal_id
                or head is None
                or not head.active
                or goal.definition.owner_id != control.owner_id
            ):
                raise ManagementDeniedError("Qualification needs its active exact owner goal")
            mandate = await current_mandate(session, scope, goal.definition.mandate)
            validate_mandate(mandate.mandate, control)
            if mandate.mandate.goals and goal.goal_id not in mandate.mandate.goals:
                raise ManagementDeniedError("Qualification goal is outside the current mandate")
            procedure = await session.scalar(
                select(ManagementProcedure).where(
                    ManagementProcedure.company_id == scope.company_id,
                    ManagementProcedure.goal_id == goal.goal_id,
                )
            )
            if procedure is not None:
                raise ManagementDeniedError("Qualification cannot reuse a delivery procedure goal")
            quote = self._quote(recipe, control, await db_now(session))
            if (
                self._allocation
                > min(
                    control.work_cap_usd,
                    control.daily_cap_usd,
                    Decimal(5),
                    mandate.mandate.work_cap_usd,
                    mandate.mandate.daily_cap_usd,
                )
                or quote.amount_usd > self._allocation
            ):
                raise ManagementDeniedError("Qualification exceeds actual fixed work/day allowance")
            task = uuid5(goal.goal_id, "nexus:model-qualification:task:v1")
            trace = uuid5(goal.goal_id, "nexus:model-qualification:trace:v1")
            ledger = LedgerScope(
                company_id=scope.company_id,
                principal_id=control.owner_id,
                task_id=task,
                trace_id=trace,
            )
            item = WorkItem(
                company_id=scope.company_id,
                task_id=task,
                trace_id=trace,
                goal_id=goal.goal_id,
                department="management",
                title="Public SDK qualification, without company completion",
                acceptance=(recipe.purpose, f"target-set:{self._target_set(recipe)}"),
                budget_usd=self._allocation,
            )
            directory = PersistentCompanyDirectory(self.factory)
            await directory.register_work_in_transaction(
                session,
                WorkRegistration(
                    company_id=scope.company_id,
                    workspace_id=identity.workspace_id,
                    task_id=task,
                    trace_id=trace,
                    actor_id=control.owner_id,
                    allocation_usd=self._allocation,
                    allowed_principals=(control.owner_id,),
                ),
                scope,
                identity,
            )
            actual = await session.get(RegisteredWork, (scope.company_id, task))
            if actual is None or not actual.active:
                raise ManagementDeniedError("Actual qualification work registration is unavailable")
            execution = await register_locked(
                session,
                ExecutionRegistration(
                    work=item,
                    run_id=uuid5(goal.goal_id, "nexus:model-qualification:run:v1"),
                    workflow_name=WORKFLOW,
                    workflow_version="v1",
                    model_profile=PROFILE,
                    model_registry_version=recipe.registry_revision,
                    quota=AttemptQuota(
                        model_requests=12, tool_attempts=0, rework_rounds=0, plan_revisions=0
                    ),
                ),
                actual,
            )
            digest = recipe_hash(recipe)
            request = qualification_request(
                recipe,
                ledger,
                action_id=uuid5(task, f"qualification-action:v1:{digest}"),
                request_id=uuid5(task, f"qualification-request:v1:{digest}"),
            )
            action = ActionProposal(
                company_id=scope.company_id,
                action_id=request.action_id,
                task_id=task,
                trace_id=trace,
                actor_id=control.owner_id,
                revision=1,
                tool=TOOL,
                tool_version="v1",
                resource=f"model-qualification:{recipe.target.registry_id}",
                parameters=qualification_parameters(recipe, request),
                policy_version=control.policy_version,
                price_version=control.price_version,
                estimated_cost_usd=quote.amount_usd,
            )
            record = await submit_pending_locked(session, control, action, ledger)
            result = PreparedQualification(
                work=snapshot(execution),
                action=record,
                request=request,
                quote=quote,
                recipe_sha256=digest,
            )
            if self._quote(recipe, control, await db_now(session)) != quote:
                raise ManagementDeniedError("Qualification financial quote changed before commit")
            return result
