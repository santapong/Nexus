"""Current native coding state, immutable request and ordinary financial quotation."""

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
from nexus.company.management.coding_content import CodingBinding, coding_schema
from nexus.company.management.coding_intent import (
    PreparedCodingRequest,
    prepare_coding_request,
    require_coding_registry,
)
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.nexus_coding_catalog import select_configured_nexus_plan
from nexus.company.management.plan_models import ManagementPlanHead, ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_input_bounds import model_input_ceiling
from nexus.core.llm.company_pricing import TokenBounds
from nexus.core.llm.company_registry import Capability
from nexus.core.llm.company_routing import ModelPolicy, RoutedModel, route_models
from nexus.execution.coding_operation import CodingOperation
from nexus.execution.coding_services import (
    VERSION,
    WORKFLOW,
    CodingServices,
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

CODING_REQUEST_CAPABILITIES: frozenset[Capability] = frozenset({"code", "structured_output"})
# C produces a typed patch without SDK tool calls. The engineering profile still
# requires model tool capability; explicit request tools retain their separate denial.


@dataclass(frozen=True)
class CodingState:
    work: ExecutionSnapshot
    goal: GoalRevisionRef
    plan_id: UUID
    plan: PlanRevisionRef
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
    operation: CodingOperation,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    *,
    lease: ExecutionLease | None = None,
) -> CodingState:
    """Actual current actor/goal/plan lineage; no lease is inferred from this projection.

    Cohesion exception: the complete same-transaction C native chain stays adjacent.
    """
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
        raise ValueError("Current registered coding child is unavailable")
    row = await session.get(ManagementPlanRevision, (scope.company_id, bound.plan.plan_revision_id))
    head = await session.get(ManagementPlanHead, (scope.company_id, bound.plan.plan_id))
    if row is None or (work.workflow_name, work.workflow_version) != (WORKFLOW, VERSION):
        raise ValueError("Coding work differs from the fixed registered workflow")
    anchor = clock_us()
    now = await db_now(session)
    credential.require_time(now)
    if lease is not None:
        require_lease(work, lease, now, execute=True)
        if lease.expires_at > credential.expires_at:
            raise ValueError("Original actor witness does not cover the actual coding lease")
        operation.shorten(now, anchor, (lease.expires_at, credential.expires_at))
    operation.require_current()
    record = plan_record(row)
    if (
        head is None
        or head.current_revision_id != record.plan_revision_id
        or select_configured_nexus_plan(services.management.catalog, record.payload) != "execution"
    ):
        raise ValueError("Coding requires its actual full approved r2 head and immutable admission")
    return CodingState(
        snapshot(work),
        plan_record(row).payload.goal,
        bound.plan.plan_id,
        plan_reference(record),
        control.policy_version,
        now,
        anchor,
    )


def prepare_content(
    services: CodingServices,
    lease: ExecutionLease,
    scope: BrainReadScope,
    context: AssembledContext,
    binding: CodingBinding,
) -> PreparedCodingRequest:
    """Server renders exact goal/context/CAS and reserves reviewed whole input before approval."""
    registry = services.management.catalog.models
    row = next(value for value in registry.models if value.registry_id == services.registry_id)
    digest = (
        canonical_sha256(binding) + canonical_sha256(registry) + canonical_sha256(services.recipe)
    )
    action_id = uuid5(lease.run_id, "coding-action:v1:" + digest)
    call = CompanyModelRequest(
        company_id=lease.company_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        actor_id=lease.actor_id,
        action_id=action_id,
        attempt_id=action_id,
        request_id=uuid5(action_id, "coding-request:v1"),
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
        output_schema=coding_schema(binding, manifest=context.manifest),
    )
    return prepare_coding_request(
        call,
        context,
        binding,
        scope=scope,
        sources=services.code_sources,
        input_recipe=services.recipe,
        catalog=services.management.catalog,
        input_estimator=services.estimator,
    )


def route_prepared(
    services: CodingServices,
    prepared: PreparedCodingRequest,
    work: ExecutionWork,
    control: CompanyControl,
    available: Decimal,
    now: datetime,
) -> RoutedModel:
    """Ordinary current eligibility, never the public-only qualification route."""
    registry, call = services.management.catalog.models, prepared.request
    row = require_coding_registry(prepared, registry)
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
        required_capabilities=CODING_REQUEST_CAPABILITIES,
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
    services: CodingServices,
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    prepared: PreparedCodingRequest,
    now: datetime,
) -> RoutedModel:
    registered = await session.get(RegisteredWork, (work.company_id, work.task_id))
    budget = await session.get(WorkBudget, (work.company_id, work.task_id))
    day = await session.get(DailyBudget, (work.company_id, billing_day(now)))
    if registered is None or not registered.active:
        raise ValueError("Coding actual own allowance is unavailable")
    # Authorization creates accounting totals lazily; quoting must not create them.
    charged = budget.held_usd + budget.spent_usd if budget else Decimal(0)
    available = min(
        registered.allocation_usd - registered.delegated_usd - charged,
        control.work_cap_usd - charged,
        control.daily_cap_usd - (day.held_usd + day.spent_usd if day else 0),
    )
    return route_prepared(services, prepared, work, control, available, now)
