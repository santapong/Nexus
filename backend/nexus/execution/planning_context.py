"""Current native planning state, immutable request and ordinary financial quotation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_query import clock_us
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import AssembledContext
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.plan_models import ManagementPlanHead, ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_content import PlanningBinding, planning_schema
from nexus.company.management.planning_intent import (
    PreparedPlanningRequest,
    prepare_planning_request,
    require_planning_registry,
)
from nexus.company.management.revision_store import plan_record
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_input_bounds import model_input_ceiling
from nexus.core.llm.company_pricing import TokenBounds
from nexus.core.llm.company_routing import ModelPolicy, RoutedModel, route_models
from nexus.execution.planning_services import (
    VERSION,
    WORKFLOW,
    PlanningOperation,
    PlanningServices,
)
from nexus.execution.runtime_contracts import ExecutionLease, ExecutionSnapshot
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    require_lease,
    snapshot,
)
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, DailyBudget, WorkBudget


@dataclass(frozen=True)
class PlanningState:
    work: ExecutionSnapshot
    goal: GoalRevisionRef
    plan_id: UUID
    head: UUID | None
    policy_version: str
    observed_at: datetime
    clock_before_us: int


def brain_scope(lease: ExecutionLease, operation_id: UUID) -> BrainReadScope:
    return BrainReadScope(
        company_id=lease.company_id,
        workspace_id=lease.workspace_id,
        principal_id=lease.actor_id,
        operation_id=operation_id,
        trace_id=lease.trace_id,
        task_id=lease.task_id,
        task_trace_id=lease.trace_id,
        actor_id=lease.actor_id,
    )


async def state_locked(
    operation: PlanningOperation,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    *,
    lease: ExecutionLease | None = None,
) -> PlanningState:
    """Actual current actor/goal/plan lineage; no lease is inferred from this projection."""
    credential, services = operation.credential, operation.services
    assert credential is not None and scope.task_id is not None and scope.task_trace_id is not None
    await services.authority.current(session, scope, credential.identity)
    work = await execution_row(
        session,
        LedgerScope(
            company_id=scope.company_id,
            principal_id=scope.principal_id,
            task_id=scope.task_id,
            trace_id=scope.task_trace_id,
        ),
    )
    bound = await ManagementPlanStore.current_binding(session, scope.company_id, scope.task_id)
    if bound is None:
        raise ValueError("Current registered planning child is unavailable")
    row = await session.get(ManagementPlanRevision, (scope.company_id, bound.plan.plan_revision_id))
    head = await session.get(ManagementPlanHead, (scope.company_id, bound.plan.plan_id))
    if row is None or (work.workflow_name, work.workflow_version) != (WORKFLOW, VERSION):
        raise ValueError("Planning work differs from the fixed registered workflow")
    anchor = clock_us()
    now = await db_now(session)
    credential.require_time(now)
    if lease is not None:
        require_lease(work, lease, now, execute=True)
        if lease.expires_at > credential.expires_at:
            raise ValueError("Original actor witness does not cover the actual planning lease")
        operation.shorten(now, anchor, (lease.expires_at, credential.expires_at))
    operation.require_current()
    return PlanningState(
        snapshot(work),
        plan_record(row).payload.goal,
        bound.plan.plan_id,
        head.current_revision_id if head else None,
        control.policy_version,
        now,
        anchor,
    )


def prepare_content(
    services: PlanningServices,
    lease: ExecutionLease,
    scope: BrainReadScope,
    context: AssembledContext,
    binding: PlanningBinding,
) -> PreparedPlanningRequest:
    """Server renders exact goal/context/CAS and reserves reviewed whole input before approval."""
    registry = services.management.catalog.models
    row = next(value for value in registry.models if value.registry_id == services.registry_id)
    digest = (
        canonical_sha256(binding) + canonical_sha256(registry) + canonical_sha256(services.recipe)
    )
    action_id = uuid5(lease.run_id, "planning-action:v1:" + digest)
    call = CompanyModelRequest(
        company_id=lease.company_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        actor_id=lease.actor_id,
        action_id=action_id,
        attempt_id=action_id,
        request_id=uuid5(action_id, "planning-request:v1"),
        registry_id=row.registry_id,
        registry_revision=registry.revision,
        price_version=registry.pricebook_version,
        data_classification=context.manifest.data_classification,
        bounds=TokenBounds(
            input_tokens=model_input_ceiling(row),
            max_output_tokens=services.max_output_tokens,
            input_bound_kind="model_input_ceiling_v1",
        ),
        input_text=context.input_text,
        system_text=context.system_text,
        output_schema=planning_schema(binding, manifest=context.manifest),
    )
    proof = services.estimator.estimate(call, registry, services.recipe)
    return prepare_planning_request(
        call, context, binding, scope=scope, input_recipe=services.recipe, input_estimate=proof
    )


def route_prepared(
    services: PlanningServices,
    prepared: PreparedPlanningRequest,
    work: ExecutionWork,
    control: CompanyControl,
    available: Decimal,
    now: datetime,
) -> RoutedModel:
    """Ordinary current eligibility, never the public-only qualification route."""
    registry, call = services.management.catalog.models, prepared.request
    row = require_planning_registry(prepared, registry)
    policy = ModelPolicy(
        company_id=work.company_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        policy_version=control.policy_version,
        pricebook_version=control.price_version,
        profile=services.recipe.profile,
        allowed_models=frozenset({row.registry_id}),
        allowed_providers=frozenset({row.provider}),
        allowed_api_families=frozenset({row.api_family}),
        data_classification=call.data_classification,
        required_capabilities=frozenset({"text", "structured_output"}),
        minimum_score=services.recipe.minimum_score,
        evaluation_suite_version=services.recipe.evaluation_suite_version,
        available_usd=max(Decimal(0), available),
        token_bounds=call.bounds,
        max_fallbacks=0,
        remaining_model_requests=work.model_requests_limit
        - work.model_requests_used
        - work.model_requests_delegated,
    )
    return route_models(
        registry, policy, now=now, model_observations=services.management.catalog.model_observations
    ).primary


async def quote_locked(
    services: PlanningServices,
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    prepared: PreparedPlanningRequest,
    now: datetime,
) -> RoutedModel:
    registered = await session.get(RegisteredWork, (work.company_id, work.task_id))
    budget = await session.get(WorkBudget, (work.company_id, work.task_id))
    day = await session.get(DailyBudget, (work.company_id, billing_day(now)))
    if registered is None or not registered.active:
        raise ValueError("Planning actual own allowance is unavailable")
    # Authorization creates accounting totals lazily; quoting must not create them.
    charged = budget.held_usd + budget.spent_usd if budget else Decimal(0)
    available = min(
        registered.allocation_usd - registered.delegated_usd - charged,
        control.work_cap_usd - charged,
        control.daily_cap_usd - (day.held_usd + day.spent_usd if day else 0),
    )
    return route_prepared(services, prepared, work, control, available, now)
