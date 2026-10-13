"""Current same-transaction model policy, catalog, quotation and input bound validation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal
from nexus.company.directory_models import RegisteredWork
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_pricing import CostQuote
from nexus.core.llm.company_registry import (
    Capability,
    DataClassification,
    ModelRegistration,
    ModelRegistry,
)
from nexus.core.llm.company_routing import ModelPolicy, route_models
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import (
    CompanyControl,
    CostHold,
    DailyBudget,
    JournalAction,
    WorkBudget,
)
from nexus.harness.model_authorizer_contracts import (
    InputEstimate,
    InputEstimator,
    ModelInputRecipe,
    model_action_parameters,
    require_input_estimate,
)


class ModelIntentCheck:
    """Trusted fast hook; all observable checks precede attempt/intent mutation."""

    def __init__(
        self,
        call: CompanyModelRequest,
        quote: CostQuote,
        lease: ExecutionLease,
        registry: ModelRegistry,
        estimator: InputEstimator,
        recipe: ModelInputRecipe,
        classification: DataClassification,
    ) -> None:
        self.call, self.quote, self.lease = call, quote, lease
        self.registry, self.estimator, self.recipe = registry, estimator, recipe
        self.classification = classification
        self.model: ModelRegistration | None = None
        self.estimate: InputEstimate | None = None
        self.billing_at: datetime | None = None
        self.hold: CostHold | None = None
        self.owner_id: UUID | None = None

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        """Recompute eligibility and quotation at DB time under the company lock."""
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        self._require_binding(proposal, action, control, work)
        hold = await session.get(CostHold, action.id)
        if hold is None or hold.state != "held" or hold.amount_usd != proposal.estimated_cost_usd:
            raise ValueError("Exact model action has no matching held allowance")
        await self._require_caps(session, control, work, now)
        model = next(
            (row for row in self.registry.models if row.registry_id == self.call.registry_id), None
        )
        if model is None:
            raise ValueError("Model is absent from the trusted catalog")
        plan = route_models(self.registry, self._policy(control, work, model, hold), now=now)
        if (
            plan.primary.model.registry_id != self.call.registry_id
            or plan.primary.quote != self.quote
        ):
            raise ValueError("Model quotation differs from current eligible catalog quotation")
        estimate = self.estimator.estimate(self.call, self.registry, self.recipe)
        require_input_estimate(self.call, estimate, self.recipe)
        self.model, self.estimate, self.billing_at, self.hold = (
            plan.primary.model,
            estimate,
            now,
            hold,
        )
        self.owner_id = control.owner_id

    def _require_binding(
        self,
        proposal: ActionProposal,
        action: JournalAction,
        control: CompanyControl,
        work: ExecutionWork,
    ) -> None:
        call = self.call
        snapshot(work)  # Validate the immutable full execution registration/digest too.
        if (
            (call.company_id, call.task_id, call.trace_id, call.actor_id)
            != (work.company_id, work.task_id, work.trace_id, work.actor_id)
            or call.action_id != proposal.action_id
            or call.attempt_id != call.action_id
            or action.approval_json is None
            or (proposal.tool, proposal.tool_version, proposal.resource)
            != ("model.request.v1", "v1", f"model:{call.registry_id}")
            or proposal.parameters != model_action_parameters(call, self.recipe)
            or (call.registry_revision, call.price_version, call.company_id)
            != (self.registry.revision, self.registry.pricebook_version, self.registry.company_id)
            or control.price_version != call.price_version
            or work.model_registry_version != self.registry.revision
            or work.model_profile != self.recipe.profile
            or call.data_classification != self.classification
            or self.lease.mode != "execute"
            or work.lease_principal_id != work.actor_id
        ):
            raise ValueError(
                "Model request does not match its current exact owner action/run/recipe"
            )

    def _policy(
        self,
        control: CompanyControl,
        work: ExecutionWork,
        model: ModelRegistration,
        hold: CostHold,
    ) -> ModelPolicy:
        required: frozenset[Capability] = frozenset({"text"})
        if self.call.tools:
            required |= frozenset({"tools"})
        if self.call.output_schema:
            required |= frozenset({"structured_output"})
        return ModelPolicy(
            company_id=work.company_id,
            task_id=work.task_id,
            trace_id=work.trace_id,
            policy_version=control.policy_version,
            pricebook_version=control.price_version,
            profile=self.recipe.profile,
            allowed_models=frozenset({model.registry_id}),
            allowed_providers=frozenset({model.provider}),
            allowed_api_families=frozenset({model.api_family}),
            data_classification=self.classification,
            required_capabilities=required,
            minimum_score=self.recipe.minimum_score,
            evaluation_suite_version=self.recipe.evaluation_suite_version,
            available_usd=hold.amount_usd,
            token_bounds=self.call.bounds,
            max_fallbacks=0,
            remaining_model_requests=work.model_requests_limit
            - work.model_requests_delegated
            - work.model_requests_used,
        )

    async def _require_caps(
        self, session: AsyncSession, control: CompanyControl, work: ExecutionWork, now: datetime
    ) -> None:
        day = await session.get(DailyBudget, (work.company_id, billing_day(now)))
        if day is not None and day.held_usd + day.spent_usd > control.daily_cap_usd:
            raise ValueError("Current model work/day allowance is exceeded")
        task: UUID | None = work.task_id
        seen: set[UUID] = set()
        for _ in range(16):
            if task is None:
                return
            registered = await session.get(RegisteredWork, (work.company_id, task))
            total = await session.get(WorkBudget, (work.company_id, task))
            if registered is None or task in seen or (task == work.task_id and total is None):
                raise ValueError("Current model work ancestry allowance is unavailable")
            seen.add(task)
            charged = total.held_usd + total.spent_usd if total else Decimal(0)
            if charged > min(
                control.work_cap_usd, registered.allocation_usd - registered.delegated_usd
            ):
                raise ValueError("Current model work/ancestor allowance is exceeded")
            task = registered.parent_task_id
        if task is not None:
            raise ValueError("Model ancestry exceeds the bounded directory lineage")
