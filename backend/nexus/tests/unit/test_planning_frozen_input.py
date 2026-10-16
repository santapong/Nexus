"""Preapproval fingerprint joins on supplied fixtures; no model/source qualification."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest

from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.planning_intent import (
    PlanningIntentCheck,
    PreparedPlanningRequest,
    prepare_planning_request,
)
from nexus.core.llm.company_adapter_contracts import request_hash
from nexus.core.llm.company_pricing import TokenBounds
from nexus.core.llm.company_registry import ModelRegistry
from nexus.harness.model_authorizer_contracts import InputEstimate, WholeRequestInputCeiling
from nexus.tests.unit.test_company_planning_consumer import planning_registry
from nexus.tests.unit.test_company_planning_intent import prepared_inputs


def frozen() -> tuple[PreparedPlanningRequest, ModelRegistry]:
    call, context, binding, scope, recipe, _ = prepared_inputs()
    registry = planning_registry("openai")
    call = call.model_copy(
        update={
            "bounds": TokenBounds(
                input_tokens=registry.models[0].context_window,
                max_output_tokens=256,
                input_bound_kind="model_input_ceiling_v1",
            )
        }
    )
    proof = InputEstimate(
        request_hash=request_hash(call),
        registry_id=call.registry_id,
        registry_revision=call.registry_revision,
        recipe_id=recipe.recipe_id,
        recipe_revision=recipe.revision,
        input_text_tokens=0,
        system_text_tokens=0,
        tool_schema_tokens=0,
        output_schema_tokens=0,
        sdk_overhead_tokens=0,
        whole_request=WholeRequestInputCeiling(
            tokens=call.bounds.input_tokens,
            registry_sha256=canonical_sha256(registry),
            model_sha256=canonical_sha256(registry.models[0]),
            recipe_sha256=canonical_sha256(recipe),
            conformance_reference=recipe.conformance_reference,
        ),
    )
    return prepare_planning_request(
        call, context, binding, scope=scope, input_recipe=recipe, input_estimate=proof
    ), registry


def context_check(prepared: PreparedPlanningRequest) -> BrainModelContextCheck:
    check = AsyncMock(spec=BrainModelContextCheck)
    check.context = prepared.context
    return cast(BrainModelContextCheck, check)


def test_preapproval_proof_is_durable_and_missing_legacy_field_stays_omitted() -> None:
    prepared, registry = frozen()
    assert (
        PreparedPlanningRequest.model_validate_json(prepared.model_dump_json(by_alias=True))
        == prepared
    )
    assert prepared.input_estimate is not None
    assert prepared.input_estimate.whole_request is not None
    assert prepared.input_estimate.whole_request.registry_sha256 == canonical_sha256(registry)
    gate = PlanningIntentCheck(context_check(prepared), prepared, registry=registry)
    assert gate.registry == registry
    call, context, binding, scope, recipe, _ = prepared_inputs()
    legacy = prepare_planning_request(call, context, binding, scope=scope, input_recipe=recipe)
    assert "input_estimate" not in legacy.model_dump()
    assert "input_estimate" not in legacy.model_dump_json(by_alias=True)


@pytest.mark.parametrize(
    "field", ["model_id", "endpoint_id", "context_window", "revision", "missing"]
)
def test_restart_cannot_relabel_approved_model_with_same_declared_revision(field: str) -> None:
    prepared, registry = frozen()
    if field == "missing":
        changed = None
    elif field == "revision":
        changed = registry.model_copy(update={"revision": "another-version"})
    else:
        value: object = (
            registry.models[0].context_window + 1 if field == "context_window" else "other-model"
        )
        changed = registry.model_copy(
            update={"models": (registry.models[0].model_copy(update={field: value}),)}
        )
    with pytest.raises(ValueError):
        PlanningIntentCheck(context_check(prepared), prepared, registry=changed)


@pytest.mark.parametrize("field", ["request_hash", "recipe_sha256", "tokens"])
def test_wrong_financial_proof_cannot_be_persisted_as_matching_preparation(field: str) -> None:
    prepared, _ = frozen()
    proof = prepared.input_estimate
    assert proof is not None and proof.whole_request is not None
    if field == "request_hash":
        changed = proof.model_copy(update={field: "f" * 64})
    else:
        value: object = proof.whole_request.tokens - 1 if field == "tokens" else "f" * 64
        changed = proof.model_copy(
            update={"whole_request": proof.whole_request.model_copy(update={field: value})}
        )
    with pytest.raises(ValueError):
        PreparedPlanningRequest.model_validate_json(
            prepared.model_copy(update={"input_estimate": changed}).model_dump_json(by_alias=True)
        )


async def test_catalog_splice_across_context_await_denied_before_more_native_reads() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.execution.runtime_models import ExecutionWork
    from nexus.harness.journal_models import CompanyControl, JournalAction

    prepared, registry = frozen()
    check = context_check(prepared)
    gate = PlanningIntentCheck(check, prepared, registry=registry)

    async def replace(*_: object) -> None:
        assert gate.registry is not None
        object.__setattr__(gate.registry, "revision", "changed-during-await")

    cast(AsyncMock, check).validate.side_effect = replace
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(ValueError, match="approved original registry/model"):
        await gate.validate(
            cast(AsyncSession, session),
            CompanyControl(company_id=prepared.request.company_id),
            ExecutionWork(company_id=prepared.request.company_id),
            JournalAction(),
            datetime.now(UTC),
        )
    session.get.assert_not_awaited()
