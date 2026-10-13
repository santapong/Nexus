"""Server recipes and exact model-action bindings cannot be replaced by caller bounds."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from nexus.core.llm.company_adapter_contracts import request_hash
from nexus.harness.model_authorizer_contracts import (
    InputEstimate,
    ModelInputRecipe,
    model_action_parameters,
    require_input_estimate,
)
from nexus.tests.unit.test_company_provider_conformance import request


def recipe() -> ModelInputRecipe:
    return ModelInputRecipe(
        recipe_id="fixture-full-request",
        revision="fixture-v1",
        profile="engineering",
        minimum_score=Decimal("0.80"),
        evaluation_suite_version="frozen-1",
        conformance_reference="fixture:estimator-not-live-conformance",
    )


def estimate() -> InputEstimate:
    call = request()
    return InputEstimate(
        request_hash=request_hash(call),
        registry_id=call.registry_id,
        registry_revision=call.registry_revision,
        recipe_id=recipe().recipe_id,
        recipe_revision=recipe().revision,
        input_text_tokens=20,
        system_text_tokens=0,
        tool_schema_tokens=0,
        output_schema_tokens=50,
        sdk_overhead_tokens=256,
    )


def test_full_estimator_evidence_and_exact_recipe_bind_the_owner_action() -> None:
    call = request()
    require_input_estimate(call, estimate(), recipe())
    parameters = model_action_parameters(call, recipe())
    assert parameters["request_hash"] == estimate().request_hash
    assert parameters["input_recipe_id"] == recipe().recipe_id
    changed = call.model_copy(update={"request_id": UUID(int=99)})
    assert model_action_parameters(changed, recipe()) != parameters


@pytest.mark.parametrize(
    "changes",
    [
        {"request_hash": "0" * 64},
        {"registry_id": "another-model"},
        {"registry_revision": "other-catalog"},
        {"recipe_id": "client-estimator"},
        {"recipe_revision": "other-recipe"},
        {"sdk_overhead_tokens": 0},
    ],
)
def test_foreign_or_incomplete_estimation_cannot_prove_the_call_bound(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        current = InputEstimate.model_validate(estimate().model_dump() | changes)
        require_input_estimate(request(), current, recipe())


def test_declared_input_bound_below_the_independent_estimate_is_denied() -> None:
    call = request()
    smaller = call.model_copy(
        update={"bounds": call.bounds.model_copy(update={"input_tokens": 100})}
    )
    adjusted = InputEstimate.model_validate(
        estimate().model_dump() | {"request_hash": request_hash(smaller)}
    )
    with pytest.raises(ValueError):
        require_input_estimate(smaller, adjusted, recipe())


@pytest.mark.parametrize("value", [True, 1.5, -1])
def test_ambiguous_or_negative_estimator_counts_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        InputEstimate.model_validate(estimate().model_dump() | {"sdk_overhead_tokens": value})


def test_recipe_hash_prevents_same_version_quality_threshold_substitution() -> None:
    current = recipe()
    changed = current.model_copy(update={"minimum_score": Decimal("0.10")})
    assert model_action_parameters(request(), current) != model_action_parameters(
        request(), changed
    )
