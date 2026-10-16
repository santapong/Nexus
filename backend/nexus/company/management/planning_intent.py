"""Freeze planning inputs before approval; recheck native goal/CAS under the existing gate."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import SHA256, BrainReadScope, ValueContract
from nexus.company.brain.context import AssembledContext
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.planning_content import PlanningBinding, planning_schema
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, request_hash
from nexus.core.llm.company_registry import ModelRegistration, ModelRegistry
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import (
    InputEstimate,
    ModelInputRecipe,
    require_input_estimate,
)


class PreparedPlanningRequest(ValueContract):
    """Descriptive server preparation; decoding this cannot authorize a provider call."""

    request: CompanyModelRequest
    context: AssembledContext
    binding: PlanningBinding
    scope: BrainReadScope
    input_recipe: ModelInputRecipe
    request_sha256: SHA256
    input_estimate: InputEstimate | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def exact_preparation(self) -> Self:
        call, context, scope = self.request, self.context, self.scope
        manifest, authority = context.manifest, context.manifest.authority
        if (
            call.tools
            or call.output_schema != planning_schema(self.binding, manifest=manifest)
            or request_hash(call) != self.request_sha256
            or canonical_sha256(manifest) != self.binding.context_manifest_sha256
            or self.binding.goal.company_id != call.company_id
            or (call.input_text, call.system_text) != (context.input_text, context.system_text)
            or (call.company_id, call.actor_id, call.task_id, call.trace_id)
            != (scope.company_id, scope.principal_id, scope.task_id, scope.task_trace_id)
            or (
                manifest.company_id,
                manifest.principal_id,
                manifest.operation_id,
                manifest.trace_id,
                manifest.task_id,
                manifest.task_trace_id,
                manifest.actor_id,
            )
            != (
                scope.company_id,
                scope.principal_id,
                scope.operation_id,
                scope.trace_id,
                scope.task_id,
                scope.task_trace_id,
                scope.actor_id,
            )
            or call.actor_id != scope.actor_id
            or call.attempt_id != call.action_id
            or call.data_classification != manifest.data_classification
            or (authority.model_profile, authority.model_recipe, authority.model_recipe_revision)
            != (self.input_recipe.profile, self.input_recipe.recipe_id, self.input_recipe.revision)
        ):
            raise ValueError("Planning schema/context/goal/scope/recipe/request pins differ")
        if self.input_estimate is not None:
            if self.input_estimate.whole_request is None:
                raise ValueError(
                    "Frozen planning input requires the complete financial fingerprint"
                )
            require_input_estimate(call, self.input_estimate, self.input_recipe)
        return self


def prepare_planning_request(
    call: CompanyModelRequest,
    context: AssembledContext,
    binding: PlanningBinding,
    *,
    scope: BrainReadScope,
    input_recipe: ModelInputRecipe,
    input_estimate: InputEstimate | None = None,
) -> PreparedPlanningRequest:
    """Run before model_action_parameters/approval, covering schema tokens and full hash."""
    prepared = PreparedPlanningRequest(
        request=call,
        context=context,
        binding=binding,
        scope=scope,
        input_recipe=input_recipe,
        request_sha256=request_hash(call),
        input_estimate=input_estimate,
    )
    return PreparedPlanningRequest.model_validate_json(prepared.model_dump_json(by_alias=True))


def require_planning_registry(
    prepared: PreparedPlanningRequest,
    registry: ModelRegistry,
) -> ModelRegistration:
    """Join reviewed private input to the original catalog/model; grant no eligibility or call."""
    proof = prepared.input_estimate
    if proof is None or proof.whole_request is None:
        raise ValueError("Planning input lacks its preapproval catalog/model fingerprint")
    require_input_estimate(prepared.request, proof, prepared.input_recipe)
    call, whole = prepared.request, proof.whole_request
    model = next((row for row in registry.models if row.registry_id == call.registry_id), None)
    if (
        model is None
        or (registry.company_id, registry.revision, registry.pricebook_version)
        != (call.company_id, call.registry_revision, call.price_version)
        or whole.registry_sha256 != canonical_sha256(registry)
        or whole.model_sha256 != canonical_sha256(model)
    ):
        raise ValueError("Planning input differs from its approved original registry/model")
    return model


class PlanningIntentCheck:
    """Actual context revalidation and native reference reads confer no new authority."""

    def __init__(
        self,
        context_check: BrainModelContextCheck,
        prepared: PreparedPlanningRequest,
        *,
        registry: ModelRegistry | None = None,
    ) -> None:
        self._context_check = context_check
        self._prepared = PreparedPlanningRequest.model_validate_json(
            prepared.model_dump_json(by_alias=True)
        )
        self._registry = (
            ModelRegistry.model_validate_json(registry.model_dump_json())
            if registry is not None
            else None
        )
        if context_check.context != self._prepared.context:
            raise ValueError("Planning context check differs from frozen preparation")
        self._require_estimate()

    @property
    def registry(self) -> ModelRegistry | None:
        """Frozen descriptive catalog for concrete guard composition; never invocation authority."""
        return self._registry

    def _require_estimate(self) -> None:
        if self._prepared.input_estimate is None:
            return  # Legacy historical/default preparation bytes remain supported.
        if self._registry is None:
            raise ValueError("Frozen planning input needs the actual configured registry")
        require_planning_registry(self._prepared, self._registry)

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        self._require_estimate()
        await self._context_check.validate(session, control, work, action, now)
        self._require_estimate()
        prepared, binding = self._prepared, self._prepared.binding
        if (
            not session.in_transaction()
            or control.company_id != binding.goal.company_id
            or (work.company_id, work.task_id) != (control.company_id, prepared.request.task_id)
            or snapshot(work).registration.work.goal_id != binding.goal.goal_id
        ):
            raise ValueError("Planning needs the original registered goal and company transaction")
        head = await session.get(ManagementGoalHead, (control.company_id, binding.goal.goal_id))
        goal = await session.get(
            ManagementGoalRevision, (control.company_id, binding.goal.revision_id)
        )
        plan = await session.get(ManagementPlanHead, (control.company_id, binding.plan_id))
        if (
            head is None
            or not head.active
            or goal is None
            or head.current_revision_id != binding.goal.revision_id
            or (goal.company_id, goal.goal_id, goal.revision_id, goal.version, goal.sha256)
            != (
                binding.goal.company_id,
                binding.goal.goal_id,
                binding.goal.revision_id,
                binding.goal.version,
                binding.goal.sha256,
            )
            or (plan.current_revision_id if plan else None) != binding.expected_plan_revision_id
            or (plan is not None and plan.goal_id != binding.goal.goal_id)
        ):
            raise ValueError("Planning goal reference or expected plan CAS is no longer current")
        self._require_estimate()
