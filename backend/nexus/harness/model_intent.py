"""Current same-transaction model policy, catalog, quotation and input bound validation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_eligibility import (
    ModelEligibilityProvenance,
    eligibility_provenance,
    validated_observations,
)
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
        *,
        model_observations: tuple[ModelEligibilityObservation, ...] = (),
    ) -> None:
        self.call, self.quote, self.lease = call, quote, lease
        self.registry, self.estimator, self.recipe = registry, estimator, recipe
        self.classification = classification
        self.observations = validated_observations(registry, model_observations)
        self.original_model: ModelRegistration | None = None
        self.eligibility_provenance: ModelEligibilityProvenance | None = None
        self._approval_expires: datetime | None = None
        self.model: ModelRegistration | None = None
        self.estimate: InputEstimate | None = None
        self.billing_at: datetime | None = None
        self.hold: CostHold | None = None
        self.owner_id: UUID | None = None
        self._prepared_policy: ModelPolicy | None = None

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
        self.original_model = model
        self.eligibility_provenance = eligibility_provenance(
            self.registry, self.observations, model
        )
        self._approval_expires = ApprovalDecision.model_validate_json(
            action.approval_json or ""
        ).expires_at
        policy = self._policy(control, work, model, hold)
        plan = route_models(self.registry, policy, now=now, model_observations=self.observations)
        if (
            plan.primary.model.registry_id != self.call.registry_id
            or plan.primary.quote != self.quote
        ):
            raise ValueError("Model quotation differs from current eligible catalog quotation")
        estimate = self.estimator.estimate(self.call, self.registry, self.recipe)
        require_input_estimate(self.call, estimate, self.recipe)
        self._require_whole_identity(estimate, model)
        self.model, self.estimate, self.billing_at, self.hold = (
            plan.primary.model,
            estimate,
            now,
            hold,
        )
        self.owner_id = control.owner_id
        self._prepared_policy = policy

    def validate_time(self, now: datetime) -> None:
        """Recheck exact price/health/evaluation window at the final intent clock.

        The prepared policy describes the one unconsumed call under the company
        mutex; our transactional quota mutation must not look like a second call.
        This performs no input estimation, DB query or provider request.
        """
        self.require_prepared_time(now)
        self.billing_at = now

    def require_prepared_time(self, now: datetime) -> None:
        """Use the same observation without moving the committed billing clock."""
        if self._prepared_policy is None or self.model is None or self.estimate is None:
            raise ValueError("Model temporal qualification has not been prepared")
        if self.estimate.whole_request is not None:
            if self.original_model is None:
                raise ValueError("Model input identity has no original catalog model")
            self._require_whole_identity(self.estimate, self.original_model)
        if (
            self._approval_expires is None
            or min(self._approval_expires, self.lease.expires_at) <= now
        ):
            raise ValueError("Model approval or lease expired before execution")
        current = route_models(
            self.registry, self._prepared_policy, now=now, model_observations=self.observations
        )
        if current.primary.model != self.model or current.primary.quote != self.quote:
            raise ValueError("Prepared model or quote changed before final intent")

    def _require_whole_identity(self, estimate: InputEstimate, model: ModelRegistration) -> None:
        """Join financial proof to actual server values, including before SDK reuse."""
        whole = estimate.whole_request
        if whole is not None and (
            whole.registry_sha256 != canonical_sha256(self.registry)
            or whole.model_sha256 != canonical_sha256(model)
        ):
            raise ValueError("Whole-input identity differs from actual registry/original model")

    def require_selection(
        self,
        request: CompanyModelRequest,
        quote: CostQuote,
        eligibility_sha256: str | None,
    ) -> None:
        provenance = self.eligibility_provenance
        if (
            request != self.call
            or quote != self.quote
            or eligibility_sha256 != (provenance.sha256 if provenance else None)
        ):
            raise ValueError("Pre-SDK qualification differs from the exact committed model request")

    async def revalidate_prepared(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        """Revalidate the already-consumed exact call, with no estimator/counter/intent mutation."""
        self._require_binding(
            ActionProposal.model_validate_json(action.proposal_json), action, control, work
        )
        await self._require_caps(session, control, work, now)
        self.require_prepared_time(now)

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
