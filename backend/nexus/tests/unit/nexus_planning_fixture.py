"""Actual context/estimator/check constructors; eligibility metadata and SQL are supplied."""

from pathlib import Path
from unittest.mock import MagicMock

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_render import render_context
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.nexus_planning_intent import NexusPlanningIntentCheck
from nexus.company.management.planning_content import PlanningBinding, planning_schema
from nexus.company.management.planning_intent import PlanningIntentCheck, prepare_planning_request
from nexus.core.llm.company_pricing import TokenBounds, quote_cost
from nexus.execution.effect_store import EffectStore
from nexus.execution.intent_checks import CompositeBeforeIntentCheck
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


async def planning_check(
    value: Boundary, effects: EffectStore, root: Path
) -> CompositeBeforeIntentCheck:
    admission = value.catalog.nexus_cycle_admission
    assert admission is not None
    bound = admission.slots[0].child.binding
    selected = recipe(profile="reasoning", evaluation_suite_version="synthetic-nexus-component")
    scope = BrainReadScope(
        company_id=bound.company_id,
        workspace_id=bound.workspace_id,
        principal_id=bound.actor_id,
        operation_id=key("planning-audit"),
        trace_id=key("planning-audit-trace"),
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
        question="Finite public contract fixture",
    )
    binding = PlanningBinding(
        goal=admission.goal,
        plan_id=admission.plan_id,
        expected_plan_revision_id=key("plan-r1"),
        context_manifest_sha256=canonical_sha256(context.manifest),
    )
    call = request(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        action_id=value.action.id,
        attempt_id=value.action.id,
        registry_id=value.catalog.models.models[0].registry_id,
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
    decision = ApprovalDecision(
        company_id=bound.company_id,
        decision_id=key("planner-decision"),
        action_id=proposal.action_id,
        action_revision=1,
        action_hash=value.action.proposal_hash,
        approver_id=value.control.owner_id,
        decision="approved",
        issued_at=value.now,
        expires_at=value.lease.expires_at,
    )
    value.action.approval_json = decision.model_dump_json()

    assembler = PersistentContextAssembler(
        effects._factory,
        MagicMock(spec=PersistentBrainRetriever),
        MagicMock(),
        limits=ContextLimits(policy_version="synthetic-context"),
    )
    check = BrainModelContextCheck(
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
        PlanningIntentCheck(check, prepared, registry=value.catalog.models), witness
    )
    model = ModelIntentCheck(
        call, quote, value.lease, value.catalog.models, estimator, selected, "internal"
    )
    return CompositeBeforeIntentCheck((planning, model, planning))
