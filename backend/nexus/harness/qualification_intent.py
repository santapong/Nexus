"""Current exact owner and native qualification intent; no ordinary eligibility bypass."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.management.control_support import current_mandate
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.governance_models import ManagementGoalHead
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_pricing import CostQuote, quote_cost
from nexus.core.llm.qualification_contracts import (
    PROFILE,
    TOOL,
    WORKFLOW,
    QualificationRecipe,
    financial_bounds,
    qualification_parameters,
    qualification_request,
    target_set_hash,
)
from nexus.execution.effect_store import EffectStore
from nexus.execution.effect_support import effect_row, require_effect_authority
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    registration_digest,
    require_lease,
    runtime_transaction,
    snapshot,
)
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, JournalAction
from nexus.harness.journal_reservations import require_current_work_caps


class QualificationIntentCheck:
    """Trusted composition, bound to the actual factory/effect store and immutable call."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        effects: EffectStore,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        recipe: QualificationRecipe,
        request: CompanyModelRequest,
    ) -> None:
        if not isinstance(effects, EffectStore) or effects._factory is not factory:
            raise ValueError("Qualification effect store must share its actual factory")
        self._factory, self._effects = factory, effects
        self._lease = ExecutionLease.model_validate_json(lease.model_dump_json(by_alias=True))
        self._identity = VerifiedIdentity.model_validate(identity.model_dump())
        self._recipe = QualificationRecipe.model_validate_json(
            recipe.model_dump_json(by_alias=True)
        )
        self._request = CompanyModelRequest.model_validate_json(
            request.model_dump_json(by_alias=True)
        )
        expected = qualification_request(
            self._recipe,
            lease_scope(self._lease),
            action_id=request.action_id,
            request_id=request.request_id,
        )
        if (
            self._lease.mode != "execute"
            or self._request != expected
            or self._identity.principal_id != self._lease.actor_id
            or self._identity.workspace_id != self._lease.workspace_id
        ):
            raise ValueError("Qualification call requires its original owner execute lease")
        self._end: datetime | None = None
        self.quote: CostQuote | None = None
        self._bound_dependencies = (factory, effects)
        self._bound_values = (self._lease, self._identity, self._recipe, self._request)

    def require_composition(self) -> None:
        if (
            self._factory is not self._bound_dependencies[0]
            or self._effects is not self._bound_dependencies[1]
            or self._effects._factory is not self._factory
            or (self._lease, self._identity, self._recipe, self._request) != self._bound_values
        ):
            raise ValueError("Qualification original native composition changed")

    def require_gate_binding(
        self,
        factory: async_sessionmaker[AsyncSession],
        effects: EffectStore,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        proposal: ActionProposal,
    ) -> None:
        """Process-local concrete mandatory gate binding; returns no portable permission."""
        self.require_composition()
        call, recipe = self._request, self._recipe
        if (
            factory is not self._factory
            or effects is not self._effects
            or lease != self._lease
            or identity != self._identity
            or (
                proposal.company_id,
                proposal.task_id,
                proposal.trace_id,
                proposal.actor_id,
                proposal.action_id,
            )
            != (call.company_id, call.task_id, call.trace_id, call.actor_id, call.action_id)
            or (proposal.tool, proposal.tool_version, proposal.resource)
            != (TOOL, "v1", f"model-qualification:{recipe.target.registry_id}")
            or proposal.price_version != call.price_version
            or proposal.parameters != qualification_parameters(recipe, call)
        ):
            raise ValueError("Qualification mandatory gate differs from original call/composition")

    def _binding(self, control: CompanyControl, work: ExecutionWork, action: JournalAction) -> None:
        self.require_composition()
        call, recipe, lease = self._request, self._recipe, self._lease
        actual = snapshot(work)
        registration = actual.registration
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        if (
            control.owner_id != self._identity.principal_id
            or work.actor_id != control.owner_id
            or work.lease_principal_id != control.owner_id
            or (work.company_id, work.task_id, work.trace_id, work.run_id, work.workspace_id)
            != (lease.company_id, lease.task_id, lease.trace_id, lease.run_id, lease.workspace_id)
            or (
                work.workflow_name,
                work.workflow_version,
                work.model_profile,
                work.model_registry_version,
            )
            != (WORKFLOW, "v1", PROFILE, recipe.registry_revision)
            or registration.work.goal_id != recipe.goal.goal_id
            or work.registration_hash != registration_digest(registration)
            or any(
                getattr(registration.quota, name) != 0
                for name in ("tool_attempts", "rework_rounds", "plan_revisions")
            )
            or registration.quota.model_requests != 12
            or registration.work.acceptance
            != (
                recipe.purpose,
                "target-set:"
                + target_set_hash(recipe.registry_revision, recipe.qualification_target_sha256s),
            )
            or (
                proposal.company_id,
                proposal.task_id,
                proposal.trace_id,
                proposal.actor_id,
                proposal.action_id,
            )
            != (call.company_id, call.task_id, call.trace_id, call.actor_id, call.action_id)
            or (proposal.tool, proposal.tool_version, proposal.resource)
            != (TOOL, "v1", f"model-qualification:{recipe.target.registry_id}")
            or proposal.parameters != qualification_parameters(recipe, call)
            or proposal.policy_version != control.policy_version
            or proposal.price_version != control.price_version
            or control.price_version != call.price_version
            or action.approval_json is None
        ):
            raise ValueError("Qualification native work/action/owner/goal binding differs")

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        if not session.in_transaction():
            raise ValueError("Qualification needs its current native transaction")
        self._binding(control, work, action)
        scope = CompanyControlScope(
            company_id=work.company_id,
            principal_id=self._identity.principal_id,
            operation_id=self._request.action_id,
            trace_id=work.trace_id,
        )
        goal = await GoalStore._current(session, scope, self._recipe.goal)
        head = await session.get(ManagementGoalHead, (work.company_id, self._recipe.goal.goal_id))
        if head is None or not head.active or goal.definition.owner_id != control.owner_id:
            raise ValueError("Qualification requires its active exact owner goal")
        await current_mandate(session, scope, goal.definition.mandate)
        hold = await session.get(CostHold, action.id)
        quote = quote_cost(self._recipe.target.price, financial_bounds(self._recipe), now=now)
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        if (
            hold is None
            or hold.state != "held"
            or hold.actual_usd is not None
            or (hold.company_id, hold.task_id) != (work.company_id, work.task_id)
            or hold.amount_usd != quote.amount_usd
            or proposal.estimated_cost_usd != quote.amount_usd
        ):
            raise ValueError("Qualification lacks its complete financial reservation")
        await require_current_work_caps(session, control, lease_scope(self._lease))
        day = await session.get(DailyBudget, (work.company_id, hold.day))
        if day is None or day.held_usd + day.spent_usd > control.daily_cap_usd:
            raise ValueError("Qualification actual day allowance is unavailable")
        approval = ApprovalDecision.model_validate_json(action.approval_json or "")
        assert self._recipe.target.price is not None
        self._end = min(
            self._lease.expires_at,
            approval.expires_at,
            self._recipe.valid_until,
            self._recipe.target.price.valid_until,
        )
        self.quote = quote
        self.validate_time(now)

    def validate_time(self, now: datetime) -> None:
        self.require_composition()
        assert self._recipe.target.price is not None
        if (
            now.utcoffset() is None
            or self._end is None
            or now
            >= min(
                self._end,
                self._recipe.valid_until,
                self._lease.expires_at,
                self._recipe.target.price.valid_until,
            )
        ):
            raise ValueError("Qualification original approval/lease/recipe/price window expired")
        if self.quote != quote_cost(
            self._recipe.target.price, financial_bounds(self._recipe), now=now
        ):
            raise ValueError("Qualification financial quote changed")

    async def revalidate_before_sdk(self) -> datetime:
        """Recheck an already consumed intent, without renewing/reserving/issuing anything."""
        self.require_composition()
        async with runtime_transaction(self._factory, lease_scope(self._lease), self._identity) as (
            session,
            control,
            _,
        ):
            work = await execution_row(session, lease_scope(self._lease))
            now = await db_now(session)
            require_lease(work, self._lease, now, execute=True)
            action = await require_effect_authority(
                session,
                control,
                work,
                self._request.action_id,
                now,
                (),
                lease_scope(self._lease),
                self._identity,
            )
            effect = await effect_row(session, work, self._request.action_id)
            if (effect.state, effect.intent_fence, effect.attempt_kind) != (
                "intent",
                self._lease.fence,
                "model_requests",
            ):
                raise ValueError("Qualification has no original uncompleted native intent")
            await self._effects.revalidate_execution_locked(
                session,
                control,
                work,
                self._identity,
                ActionProposal.model_validate_json(action.proposal_json),
                "model_requests",
            )
            await self.validate(session, control, work, action, await db_now(session))
            final = await db_now(session)
            hold = await session.get(CostHold, self._request.action_id)
            if (
                hold is None
                or hold.day != billing_day(final)
                or hold.day != billing_day(effect.created_at)
            ):
                raise ValueError("Qualification intent cannot cross its reserved billing day")
            require_lease(work, self._lease, final, execute=True)
            self.validate_time(final)
            return final

    async def observation_time(self) -> datetime:
        """Issued evidence may be preserved after revocation; this read grants no new call."""
        self.require_composition()
        async with self._factory() as session:
            return await db_now(session)
