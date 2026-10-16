"""Actual request/whole-input proof construction with supplied context, no registered DB proof."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_render import render_context
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.management.planning_content import PlanningBinding
from nexus.company.management.planning_intent import (
    PreparedPlanningRequest,
    require_planning_registry,
)
from nexus.core.llm.company_routing import RoutingDeniedError
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.planning_context import prepare_content, quote_locked, route_prepared
from nexus.execution.planning_services import PlanningServices
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CompanyControl, DailyBudget, WorkBudget
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.tests.unit.test_company_brain_context_render import head, material
from nexus.tests.unit.test_company_planning_intent import prepared_inputs
from nexus.tests.unit.test_company_provider_conformance import NOW
from nexus.tests.unit.test_planning_services import services


def quote_services(tmp_path: Path) -> PlanningServices:
    """Match supplied evaluation suite to the configured recipe; never a live quality claim."""
    original = services(tmp_path)
    registry = original.management.catalog.models
    row = registry.models[0]
    row = row.model_copy(
        update={
            "evaluations": tuple(
                value.model_copy(update={"suite_version": original.recipe.evaluation_suite_version})
                for value in row.evaluations
            )
        }
    )
    registry = type(registry).model_validate(registry.model_dump() | {"models": (row,)})
    catalog = original.management.catalog
    management = ManagementExecutionServices(
        type(catalog).model_validate(catalog.model_dump() | {"models": registry}),
        original.management.artifacts,
        original.management.freshness,
    )
    authority = ManagementPlanningAuthority(management, original.authority.policy, original.recipe)
    contexts = PersistentContextAssembler(
        original.factory,
        original.contexts._retriever,
        authority,
        limits=original.contexts._limits,
    )
    return replace(
        original,
        management=management,
        contexts=contexts,
        estimator=FullContextInputEstimator(registry, original.recipe),
    )


def prepared_request(configured: PlanningServices) -> PreparedPlanningRequest:
    """Actual server request assembly with supplied context, without SQL or SDK calls."""
    _, old, binding, scope, _, lease = prepared_inputs()
    authority = old.manifest.authority.model_copy(
        update={
            "model_recipe": configured.recipe.recipe_id,
            "model_recipe_revision": configured.recipe.revision,
        }
    )
    item = material()
    context = render_context(
        scope,
        authority,
        ContextLimits(policy_version="context-v1"),
        (item,),
        (head(item),),
        question="Current goal DATA",
    )
    binding = PlanningBinding.model_validate(
        binding.model_dump() | {"context_manifest_sha256": canonical_sha256(context.manifest)}
    )
    return prepare_content(configured, lease, scope, context, binding)


def test_server_request_binds_whole_context_goal_head_and_registry_before_approval(
    tmp_path: Path,
) -> None:
    configured = quote_services(tmp_path)
    prepared = prepared_request(configured)
    _, _, binding, _, _, lease = prepared_inputs()
    assert prepared.input_estimate is not None
    assert prepared.input_estimate.whole_request is not None
    assert prepared.request.bounds.input_tokens == 400_000
    assert prepared.request.bounds.max_output_tokens == 256
    assert prepared.request.input_text == prepared.context.input_text
    assert prepared.request.system_text == prepared.context.system_text
    assert prepared.request.actor_id == lease.actor_id
    assert prepared.request.attempt_id == prepared.request.action_id
    assert prepared.binding.goal == binding.goal
    assert prepared.binding.plan_id == binding.plan_id
    assert prepared.binding.expected_plan_revision_id == binding.expected_plan_revision_id
    assert prepared.binding.context_manifest_sha256 == canonical_sha256(prepared.context.manifest)
    require_planning_registry(prepared, configured.management.catalog.models)


def quote_rows() -> tuple[ExecutionWork, RegisteredWork, CompanyControl]:
    """Fresh real ORM rows; registration grants allowance before accounting totals exist."""
    work = ExecutionWork(
        company_id=UUID(int=1),
        task_id=UUID(int=6),
        trace_id=UUID(int=7),
        model_requests_limit=3,
        model_requests_used=0,
        model_requests_delegated=0,
    )
    registered = RegisteredWork(
        company_id=work.company_id,
        task_id=work.task_id,
        allocation_usd=Decimal("3"),
        delegated_usd=Decimal("1"),
        active=True,
    )
    control = CompanyControl(
        company_id=work.company_id,
        policy_version="policy-1",
        price_version="prices-1",
        work_cap_usd=Decimal("3"),
        daily_cap_usd=Decimal("5"),
    )
    return work, registered, control


def quote_session(
    registered: RegisteredWork | None,
    total: WorkBudget | None = None,
    daily: DailyBudget | None = None,
) -> AsyncMock:
    """Supply only the three actual read results; every mutation surface stays observable."""
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = (registered, total, daily)
    return session


def require_read_only(session: AsyncMock) -> None:
    session.add.assert_not_called()
    session.add_all.assert_not_called()
    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.execute.assert_not_awaited()


async def test_fresh_registered_work_quotes_without_creating_accounting_totals(
    tmp_path: Path,
) -> None:
    configured = quote_services(tmp_path)
    prepared = prepared_request(configured)
    work, registered, control = quote_rows()
    session = quote_session(registered)
    selected = await quote_locked(
        configured, cast(AsyncSession, session), control, work, prepared, NOW
    )
    assert selected == route_prepared(configured, prepared, work, control, Decimal("2"), NOW)
    assert session.get.await_args_list[0].args == (
        RegisteredWork,
        (work.company_id, work.task_id),
    )
    assert session.get.await_args_list[2].args == (
        DailyBudget,
        (work.company_id, billing_day(NOW)),
    )
    require_read_only(session)


@pytest.mark.parametrize("missing", [True, False])
async def test_quote_requires_actual_active_registered_allowance(
    tmp_path: Path, missing: bool
) -> None:
    configured = quote_services(tmp_path)
    work, registered, control = quote_rows()
    registered.active = False
    session = quote_session(None if missing else registered)
    with pytest.raises(ValueError, match="own allowance"):
        await quote_locked(
            configured,
            cast(AsyncSession, session),
            control,
            work,
            prepared_request(configured),
            NOW,
        )
    require_read_only(session)


@pytest.mark.parametrize("boundary", ["allocation", "work-cap", "day-cap"])
@pytest.mark.parametrize("shortfall", [Decimal(0), Decimal("0.000001")])
async def test_existing_held_and_spent_totals_constrain_each_current_allowance(
    tmp_path: Path, boundary: str, shortfall: Decimal
) -> None:
    configured = quote_services(tmp_path)
    prepared = prepared_request(configured)
    work, registered, control = quote_rows()
    total = WorkBudget(held_usd=Decimal("0.3"), spent_usd=Decimal("0.2"))
    daily = DailyBudget(held_usd=Decimal("0.8"), spent_usd=Decimal("0.2"))
    required = route_prepared(configured, prepared, work, control, Decimal("2"), NOW).quote
    available = required.amount_usd - shortfall
    if boundary == "allocation":
        registered.allocation_usd = registered.delegated_usd + Decimal("0.5") + available
    elif boundary == "work-cap":
        control.work_cap_usd = Decimal("0.5") + available
    else:
        control.daily_cap_usd = Decimal("1") + available
    session = quote_session(registered, total, daily)
    if shortfall:
        with pytest.raises(RoutingDeniedError, match="budget"):
            await quote_locked(
                configured, cast(AsyncSession, session), control, work, prepared, NOW
            )
    else:
        selected = await quote_locked(
            configured, cast(AsyncSession, session), control, work, prepared, NOW
        )
        assert selected.quote == required
    assert (total.held_usd, total.spent_usd) == (Decimal("0.3"), Decimal("0.2"))
    assert (daily.held_usd, daily.spent_usd) == (Decimal("0.8"), Decimal("0.2"))
    require_read_only(session)


async def test_fresh_totals_do_not_restore_used_or_delegated_model_requests(tmp_path: Path) -> None:
    configured = quote_services(tmp_path)
    work, registered, control = quote_rows()
    work.model_requests_used, work.model_requests_delegated = 1, 2
    session = quote_session(registered)
    with pytest.raises(RoutingDeniedError, match="allowance exhausted"):
        await quote_locked(
            configured,
            cast(AsyncSession, session),
            control,
            work,
            prepared_request(configured),
            NOW,
        )
    assert (work.model_requests_used, work.model_requests_delegated) == (1, 2)
    require_read_only(session)


async def test_existing_daily_spend_still_denies_work_without_lifetime_totals(
    tmp_path: Path,
) -> None:
    configured = quote_services(tmp_path)
    work, registered, control = quote_rows()
    daily = DailyBudget(held_usd=Decimal("2"), spent_usd=Decimal("3"))
    session = quote_session(registered, daily=daily)
    with pytest.raises(RoutingDeniedError, match="budget"):
        await quote_locked(
            configured,
            cast(AsyncSession, session),
            control,
            work,
            prepared_request(configured),
            NOW,
        )
    require_read_only(session)
