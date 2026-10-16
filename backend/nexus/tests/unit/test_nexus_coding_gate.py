"""Actual fresh EffectStore boundary over supplied SQL/authority; no database or model call."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_render import render_context
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.nexus_planning_intent import NexusPlanningIntentCheck
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.planning_content import PlanningBinding, planning_schema
from nexus.company.management.planning_intent import PlanningIntentCheck, prepare_planning_request
from nexus.core.llm.company_pricing import TokenBounds, quote_cost
from nexus.execution.effect_store import EffectStore
from nexus.execution.intent_checks import CompositeBeforeIntentCheck
from nexus.execution.planning_application import compose_planning_application
from nexus.harness.canonical import action_hash
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.harness.model_intent import ModelIntentCheck
from nexus.tests.unit.nexus_cycle_fixture import key
from nexus.tests.unit.nexus_intent_fixture import Boundary
from nexus.tests.unit.nexus_report_fixture import credentials
from nexus.tests.unit.test_company_brain_context_render import authority
from nexus.tests.unit.test_company_input_estimator import recipe
from nexus.tests.unit.test_company_provider_conformance import request
from nexus.tests.unit.test_nexus_coding_catalog import coding_case, coding_configuration
from nexus.tests.unit.test_nexus_coding_planner import base_plan
from nexus.tests.unit.test_planning_application import (
    TEST_SIGNER,
    SuppliedCredential,
    application_settings,
)


def coding_boundary(monkeypatch: pytest.MonkeyPatch, index: int = 0) -> Boundary:
    from nexus.tests.unit import nexus_intent_fixture as fixture

    monkeypatch.setattr(fixture, "case", coding_case)
    return fixture.boundary(index)


async def concrete_checks(
    value: Boundary, effects: EffectStore, root: Path
) -> CompositeBeforeIntentCheck:
    """Cohesion exception: real prepared/context/estimator/check constructors share all pins."""
    admission = value.catalog.nexus_coding_admission
    assert admission is not None
    config = coding_configuration(root).model_copy(update={"catalog": value.catalog})
    factory = async_sessionmaker[AsyncSession]()
    application = compose_planning_application(
        factory, config, application_settings(), SuppliedCredential(), SecretStr(TEST_SIGNER)
    )
    value.catalog = application.runtime.management.catalog
    effects._management_catalog = value.catalog
    effects._factory = factory
    bound = admission.slots[0].child.binding
    selected = recipe(profile="reasoning", evaluation_suite_version="synthetic-nexus-component")
    scope = BrainReadScope(
        company_id=bound.company_id,
        workspace_id=bound.workspace_id,
        principal_id=bound.actor_id,
        operation_id=key("coding-L-audit"),
        trace_id=key("coding-L-audit-trace"),
        task_id=bound.task_id,
        task_trace_id=bound.trace_id,
        actor_id=bound.actor_id,
    )
    state = authority().model_copy(
        update={
            "company_id": bound.company_id,
            "data_classification": "internal",
            "model_profile": selected.profile,
            "model_recipe": selected.recipe_id,
            "model_recipe_revision": selected.revision,
            "feedback": (),
        }
    )
    context = render_context(
        scope,
        state,
        ContextLimits(policy_version="synthetic-context"),
        (),
        (),
        question="supplied L DATA",
    )
    record = base_plan(admission)
    binding = PlanningBinding(
        goal=admission.goal,
        plan_id=admission.plan_id,
        expected_plan_revision_id=record.plan_revision_id,
        context_manifest_sha256=canonical_sha256(context.manifest),
    )
    call = request(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        action_id=value.action.id,
        attempt_id=value.action.id,
        registry_id=admission.slots[0].tool.resource.removeprefix("model:"),
        registry_revision=value.catalog.models.revision,
        price_version=value.catalog.models.pricebook_version,
        data_classification="internal",
        input_text=context.input_text,
        system_text=context.system_text,
        bounds=TokenBounds(
            input_tokens=400000, max_output_tokens=512, input_bound_kind="model_input_ceiling_v1"
        ),
        output_schema=planning_schema(binding, manifest=context.manifest),
    )
    estimator = FullContextInputEstimator(value.catalog.models, selected)
    estimate = estimator.estimate(call, value.catalog.models, selected)
    prepared = prepare_planning_request(
        call, context, binding, scope=scope, input_recipe=selected, input_estimate=estimate
    )
    quote = quote_cost(value.catalog.models.models[0].price, call.bounds, now=value.now)
    proposal = ActionProposal.model_validate_json(value.action.proposal_json).model_copy(
        update={
            "parameters": model_action_parameters(call, selected),
            "estimated_cost_usd": quote.amount_usd,
        }
    )
    value.action.proposal_json = proposal.model_dump_json()
    value.action.proposal_hash = action_hash(proposal)
    value.hold.amount_usd = quote.amount_usd
    value.action.approval_json = ApprovalDecision(
        company_id=bound.company_id,
        decision_id=key("coding-L-decision"),
        action_id=value.action.id,
        action_revision=1,
        action_hash=value.action.proposal_hash,
        approver_id=value.control.owner_id,
        decision="approved",
        issued_at=value.now,
        expires_at=value.lease.expires_at,
    ).model_dump_json()
    assembler = application.runtime.contexts
    brain = BrainModelContextCheck(
        assembler,
        context,
        scope,
        value.identity,
        call,
        selected,
        value.lease,
        allowed_classification="internal",
    )
    witness = await credentials(bound).current(bound)
    planning = NexusPlanningIntentCheck(
        PlanningIntentCheck(brain, prepared, registry=value.catalog.models),
        witness,
        catalog=value.catalog,
    )
    model = ModelIntentCheck(
        call, quote, value.lease, value.catalog.models, estimator, selected, "internal"
    )
    previous = value.session.get.side_effect

    async def get(model_type: type[object], selector: object) -> object | None:
        if model_type is ManagementPlanRevision:
            return ManagementPlanRevision(
                company_id=record.company_id,
                plan_id=record.plan_id,
                plan_revision_id=record.plan_revision_id,
                revision=1,
                sha256=record.sha256,
                snapshot_json=record.payload.model_dump_json(),
                proposed_by=value.control.owner_id,
                recorded_at=value.now,
            )
        delivered: object | None = await previous(model_type, selector)
        return delivered

    value.session.get = AsyncMock(side_effect=get)
    return CompositeBeforeIntentCheck((planning, model, planning))


@pytest.mark.parametrize("index", range(10))
@pytest.mark.parametrize("noop", [False, True])
async def test_new_profile_never_falls_back_to_ordinary_fresh_effect(
    monkeypatch: pytest.MonkeyPatch,
    index: int,
    noop: bool,
) -> None:
    value = coding_boundary(monkeypatch, index)
    effects = value.install(monkeypatch)
    check = AsyncMock() if noop else None
    with pytest.raises(ValueError):
        await effects.begin(
            value.lease,
            value.identity,
            value.action.id,
            kind="model_requests" if index < 5 else "tool_attempts",
            before_intent=check,
        )
    assert not value.added and value.work.model_requests_used == value.work.tool_attempts_used == 0
    assert value.hold.state == "held"
    value.move.assert_not_awaited()


async def test_full_profile_l_requires_real_original_composite_and_persisted_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value = coding_boundary(monkeypatch)
    effects = value.install(monkeypatch)
    checks = await concrete_checks(value, effects, tmp_path)
    monkeypatch.setattr(PlanningIntentCheck, "validate", AsyncMock())
    monkeypatch.setattr(ModelIntentCheck, "_require_caps", AsyncMock())
    result = await effects.begin(
        value.lease, value.identity, value.action.id, kind="model_requests", before_intent=checks
    )
    assert result.permit_external_call and value.work.model_requests_used == 1
    assert value.work.tool_attempts_used == 0 and len(value.added) == 2


async def test_changed_durable_native_digest_denies_before_any_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value = coding_boundary(monkeypatch)
    effects = value.install(monkeypatch)
    checks = await concrete_checks(value, effects, tmp_path)
    previous = value.session.get.side_effect

    async def get(model: type[object], selector: object) -> object | None:
        row: object | None = await previous(model, selector)
        if isinstance(row, ManagementPlanRevision):
            import json

            payload = json.loads(row.snapshot_json)
            payload["coding_admission_sha256"] = "f" * 64
            row.snapshot_json = json.dumps(payload)
        return row

    value.session.get = AsyncMock(side_effect=get)
    monkeypatch.setattr(PlanningIntentCheck, "validate", AsyncMock())
    monkeypatch.setattr(ModelIntentCheck, "_require_caps", AsyncMock())
    with pytest.raises(ValueError):
        await effects.begin(
            value.lease,
            value.identity,
            value.action.id,
            kind="model_requests",
            before_intent=checks,
        )
    assert not value.added and value.work.model_requests_used == 0


async def test_new_planner_rejects_hidden_authority_swap_in_same_context_assembler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value = coding_boundary(monkeypatch)
    effects = value.install(monkeypatch)
    checks = await concrete_checks(value, effects, tmp_path)
    planning = checks._checks[0]
    assert type(planning) is NexusPlanningIntentCheck
    assembler = planning._context_check._revalidator
    assert type(assembler) is PersistentContextAssembler
    assembler._authority = MagicMock()
    monkeypatch.setattr(PlanningIntentCheck, "validate", AsyncMock())
    monkeypatch.setattr(ModelIntentCheck, "_require_caps", AsyncMock())
    with pytest.raises(ValueError):
        await effects.begin(
            value.lease,
            value.identity,
            value.action.id,
            kind="model_requests",
            before_intent=checks,
        )
    assert not value.added and value.work.model_requests_used == 0
