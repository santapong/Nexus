"""Actual native model predicates on supplied rows; no DB/provider qualification.

Full-context ceilings narrow finance only; data permission stays with actual server policy.
"""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.management.canonical import canonical_sha256
from nexus.core.llm.company_adapter_contracts import CompanyModelResult
from nexus.core.llm.company_pricing import TokenUsage, quote_cost
from nexus.core.llm.company_registry import DataClassification, ModelRegistry
from nexus.execution.runtime_contracts import ExecutionRegistration
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.canonical import action_hash
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
    ModelInputRecipe,
    model_action_parameters,
)
from nexus.harness.model_evidence import ModelEvidence
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.harness.model_intent import ModelIntentCheck
from nexus.tests.unit.test_company_input_bounds import bounds, supported
from nexus.tests.unit.test_company_input_estimator import recipe
from nexus.tests.unit.test_company_provider_conformance import NOW, request
from nexus.tests.unit.test_qualification_intent import native


class SuppliedEstimate:
    """Deliver a real constructed estimate or one precise adversarial hash splice."""

    def __init__(self, result: InputEstimate) -> None:
        self.result = result

    def estimate(
        self, call: object, registry: ModelRegistry, recipe: ModelInputRecipe
    ) -> InputEstimate:
        return self.result


async def model_check(
    classification: DataClassification = "public",
) -> tuple[ModelIntentCheck, AsyncSession, CompanyControl, ExecutionWork, JournalAction]:
    original, session, control, work, action, _ = native()
    registry = supported()
    registry = ModelRegistry.model_validate(
        registry.model_dump()
        | {
            "models": (
                registry.models[0].model_dump()
                | {"allowed_data": frozenset({"public", "internal"})},
            )
        }
    )
    selected = recipe(evaluation_suite_version="frozen-1")
    lease = original._lease.model_copy(update={"expires_at": NOW + timedelta(minutes=5)})
    call = request(
        task_id=work.task_id,
        trace_id=work.trace_id,
        actor_id=work.actor_id,
        action_id=action.id,
        attempt_id=action.id,
        bounds=bounds(),
        data_classification=classification,
    )
    quote = quote_cost(registry.models[0].price, call.bounds, now=NOW)
    proposal = ActionProposal.model_validate_json(action.proposal_json).model_copy(
        update={
            "tool": "model.request.v1",
            "resource": f"model:{call.registry_id}",
            "parameters": model_action_parameters(call, selected),
            "price_version": call.price_version,
            "estimated_cost_usd": quote.amount_usd,
        }
    )
    approval = ApprovalDecision.model_validate_json(action.approval_json or "").model_copy(
        update={
            "issued_at": NOW,
            "expires_at": NOW + timedelta(minutes=4),
            "action_hash": action_hash(proposal),
        }
    )
    action.proposal_json, action.proposal_hash = proposal.model_dump_json(), action_hash(proposal)
    action.approval_json = approval.model_dump_json()
    control.price_version = call.price_version
    registered = ExecutionRegistration.model_validate_json(work.registration_json).model_copy(
        update={
            "model_profile": selected.profile,
            "model_registry_version": registry.revision,
        }
    )
    work.registration_json, work.registration_hash = (
        registered.model_dump_json(),
        registration_digest(registered),
    )
    work.model_profile, work.model_registry_version = selected.profile, registry.revision
    work.lease_until = lease.expires_at
    for model in (CostHold, DailyBudget, WorkBudget):
        key = (
            (work.company_id, billing_day(NOW))
            if model is DailyBudget
            else (work.company_id, work.task_id)
        )
        row = await session.get(model, action.id if model is CostHold else key)
        assert row is not None
        if isinstance(row, CostHold):
            row.amount_usd = quote.amount_usd
        else:
            assert isinstance(row, (DailyBudget, WorkBudget))
            row.held_usd = quote.amount_usd
    check = ModelIntentCheck(
        call,
        quote,
        lease,
        registry,
        FullContextInputEstimator(registry, selected),
        selected,
        classification,
    )
    return check, session, control, work, action


@pytest.mark.parametrize("field", ["registry_sha256", "model_sha256"])
async def test_native_intent_rejects_proof_from_foreign_registry_or_original_model(
    field: str,
) -> None:
    check, session, control, work, action = await model_check()
    await check.validate(session, control, work, action, NOW)
    assert check.estimate is not None and check.estimate.whole_request is not None
    wrong = check.estimate.model_copy(
        update={"whole_request": check.estimate.whole_request.model_copy(update={field: "f" * 64})}
    )
    check.estimator = SuppliedEstimate(wrong)
    with pytest.raises(ValueError, match="identity"):
        await check.validate(session, control, work, action, NOW)


@pytest.mark.parametrize("field", ["registry_sha256", "model_sha256"])
async def test_pre_sdk_prepared_time_rechecks_original_whole_proof(field: str) -> None:
    check, session, control, work, action = await model_check()
    await check.validate(session, control, work, action, NOW)
    assert check.estimate is not None and check.estimate.whole_request is not None
    check.estimate = check.estimate.model_copy(
        update={"whole_request": check.estimate.whole_request.model_copy(update={field: "f" * 64})}
    )
    with pytest.raises(ValueError, match="identity"):
        check.require_prepared_time(NOW)


def test_saved_whole_model_hash_must_match_original_model() -> None:
    registry, selected = supported(), recipe()
    call = request(bounds=bounds(), data_classification="public")
    estimate = FullContextInputEstimator(registry, selected).estimate(call, registry, selected)
    evidence = ModelEvidence(
        request=call,
        request_hash=estimate.request_hash,
        action_hash="a" * 64,
        model=registry.models[0],
        registry_revision=registry.revision,
        price_version=registry.pricebook_version,
        recipe=selected,
        input_estimate=estimate,
        result=CompanyModelResult(
            request_id=call.request_id,
            status="response",
            billing="known",
            usage=TokenUsage(input_tokens=100, output_tokens=20),
        ),
        source_event_at=NOW,
        checked_at=NOW,
        owner_id=call.actor_id,
    )
    evidence.require_binding()
    assert estimate.whole_request is not None
    wrong = estimate.model_copy(
        update={
            "whole_request": estimate.whole_request.model_copy(update={"model_sha256": "f" * 64})
        }
    )
    with pytest.raises(ValueError, match="model"):
        evidence.model_copy(update={"input_estimate": wrong}).require_binding()


def test_normal_financial_estimation_honors_allowed_internal_policy() -> None:
    registry, selected = supported(), recipe()
    registry = ModelRegistry.model_validate(
        registry.model_dump()
        | {
            "models": (
                registry.models[0].model_dump()
                | {"allowed_data": frozenset({"public", "internal"})},
            )
        }
    )
    call = request(bounds=bounds(), data_classification="internal")
    estimated = FullContextInputEstimator(registry, selected).estimate(call, registry, selected)
    assert estimated.whole_request is not None
    assert estimated.whole_request.registry_sha256 == canonical_sha256(registry)
    assert estimated.total_tokens == call.bounds.input_tokens


async def test_actual_native_predicates_accept_explicit_internal_policy_and_reject_splice() -> None:
    check, session, control, work, action = await model_check("internal")
    await check.validate(session, control, work, action, NOW)
    check.require_prepared_time(NOW)
    check.classification = "public"
    with pytest.raises(ValueError, match="owner action"):
        await check.validate(session, control, work, action, NOW)


def test_estimator_cannot_expand_public_only_registry_to_internal() -> None:
    registry, selected = supported(), recipe()
    with pytest.raises(ValueError, match="data policy"):
        FullContextInputEstimator(registry, selected).estimate(
            request(bounds=bounds(), data_classification="internal"), registry, selected
        )
