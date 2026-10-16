"""Freeze planning inputs before approval; recheck native goal/CAS under the existing gate."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import SHA256, BrainReadScope, ValueContract
from nexus.company.brain.context import AssembledContext
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.planning_content import PlanningBinding, planning_schema
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, request_hash
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import ModelInputRecipe


class PreparedPlanningRequest(ValueContract):
    """Descriptive server preparation; decoding this cannot authorize a provider call."""

    request: CompanyModelRequest
    context: AssembledContext
    binding: PlanningBinding
    scope: BrainReadScope
    input_recipe: ModelInputRecipe
    request_sha256: SHA256

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
        return self


def prepare_planning_request(
    call: CompanyModelRequest,
    context: AssembledContext,
    binding: PlanningBinding,
    *,
    scope: BrainReadScope,
    input_recipe: ModelInputRecipe,
) -> PreparedPlanningRequest:
    """Run before model_action_parameters/approval, covering schema tokens and full hash."""
    prepared = PreparedPlanningRequest(
        request=call,
        context=context,
        binding=binding,
        scope=scope,
        input_recipe=input_recipe,
        request_sha256=request_hash(call),
    )
    return PreparedPlanningRequest.model_validate_json(prepared.model_dump_json(by_alias=True))


class PlanningIntentCheck:
    """Actual context revalidation and native reference reads confer no new authority."""

    def __init__(
        self, context_check: BrainModelContextCheck, prepared: PreparedPlanningRequest
    ) -> None:
        self._context_check = context_check
        self._prepared = PreparedPlanningRequest.model_validate_json(
            prepared.model_dump_json(by_alias=True)
        )
        if context_check.context != self._prepared.context:
            raise ValueError("Planning context check differs from frozen preparation")

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        await self._context_check.validate(session, control, work, action, now)
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
