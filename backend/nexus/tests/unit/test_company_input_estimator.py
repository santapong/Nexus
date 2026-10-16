"""Finite supplied catalog data; source conformance is not a live provider evaluation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from nexus.company.management.canonical import canonical_sha256
from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument, ModelTool, request_hash
from nexus.core.llm.company_registry import ModelRegistry
from nexus.harness import model_input_estimator as estimator_module
from nexus.harness.model_authorizer_contracts import (
    InputEstimate,
    ModelInputRecipe,
    require_input_estimate,
)
from nexus.harness.model_input_estimator import (
    RECIPE_ID,
    RECIPE_REVISION,
    FullContextInputEstimator,
    input_conformance_reference,
)
from nexus.tests.unit.test_company_input_bounds import bounds, supported
from nexus.tests.unit.test_company_model_authorizer import estimate as old_estimate
from nexus.tests.unit.test_company_provider_conformance import request


def recipe(**changes: object) -> ModelInputRecipe:
    return ModelInputRecipe.model_validate(
        {
            "recipe_id": RECIPE_ID,
            "revision": RECIPE_REVISION,
            "profile": "engineering",
            "minimum_score": Decimal("0.8"),
            "evaluation_suite_version": "supplied-not-live-evaluation",
            "conformance_reference": input_conformance_reference(),
        }
        | changes
    )


@pytest.mark.parametrize("provider", ["openai", "google"])
@pytest.mark.parametrize("system", [None, "Public system instruction"])
@pytest.mark.parametrize("schema", [False, True])
def test_exact_whole_request_has_no_invented_component_counts(
    provider: str, system: str | None, schema: bool
) -> None:
    registry, current_recipe = supported(provider), recipe()
    call = request(
        bounds=bounds(provider),
        data_classification="public",
        system_text=system,
        **({} if schema else {"output_schema": None}),
    )
    result = FullContextInputEstimator(registry, current_recipe).estimate(
        call, registry, current_recipe
    )
    require_input_estimate(call, result, current_recipe)
    assert result.total_tokens == call.bounds.input_tokens
    assert result.request_hash == request_hash(call)
    assert result.whole_request is not None
    assert result.whole_request.registry_sha256 == canonical_sha256(registry)
    assert result.whole_request.model_sha256 == canonical_sha256(registry.models[0])
    assert result.whole_request.recipe_sha256 == canonical_sha256(current_recipe)
    assert all(
        value == 0
        for value in (
            result.input_text_tokens,
            result.system_text_tokens,
            result.tool_schema_tokens,
            result.output_schema_tokens,
            result.sdk_overhead_tokens,
        )
    )
    assert InputEstimate.model_validate_json(result.model_dump_json()) == result


def test_default_component_estimate_codec_omits_the_new_optional_field() -> None:
    original = old_estimate()
    assert "whole_request" not in original.model_dump()
    assert "whole_request" not in original.model_dump_json()
    assert original.total_tokens == 326


@pytest.mark.parametrize(
    "change",
    [
        {"recipe_id": "client-made"},
        {"revision": "v2"},
        {"conformance_reference": "random-string-is-not-source-evidence"},
    ],
)
def test_constructor_rejects_unreviewed_recipe_identity(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        FullContextInputEstimator(supported(), recipe(**change))


@pytest.mark.parametrize("field", ["minimum_score", "evaluation_suite_version", "profile"])
def test_same_recipe_version_cannot_change_constructor_snapshot(field: str) -> None:
    registry, original = supported(), recipe()
    estimator = FullContextInputEstimator(registry, original)
    changes: dict[str, object] = {
        "minimum_score": Decimal("0.1"),
        "evaluation_suite_version": "other",
        "profile": "routine",
    }
    changed = ModelInputRecipe.model_validate(original.model_dump() | {field: changes[field]})
    with pytest.raises(ValueError):
        estimator.estimate(
            request(bounds=bounds(), data_classification="public"), registry, changed
        )


@pytest.mark.parametrize(
    "change",
    [
        {"endpoint_id": "another-server-endpoint"},
        {"enabled": False},
        {"model_id": "gpt-5.4-mini"},
        {"context_window": 400_001},
    ],
)
def test_same_registry_version_cannot_replace_original_values(change: dict[str, object]) -> None:
    original, current_recipe = supported(), recipe()
    estimator = FullContextInputEstimator(original, current_recipe)
    changed = ModelRegistry.model_validate(
        original.model_dump() | {"models": (original.models[0].model_dump() | change,)}
    )
    with pytest.raises(ValueError):
        estimator.estimate(
            request(bounds=bounds(), data_classification="public"), changed, current_recipe
        )


@pytest.mark.parametrize(
    "change",
    [
        {"company_id": UUID(int=99)},
        {"registry_revision": "another-revision"},
        {"price_version": "another-price"},
        {"registry_id": "absent"},
        {"data_classification": "internal"},
    ],
)
def test_request_must_join_constructor_company_catalog_and_allowed_data(
    change: dict[str, object],
) -> None:
    registry, current_recipe = supported(), recipe()
    with pytest.raises(ValueError):
        FullContextInputEstimator(registry, current_recipe).estimate(
            request(**({"bounds": bounds(), "data_classification": "public"} | change)),
            registry,
            current_recipe,
        )


def test_function_tools_cannot_use_the_initial_whole_input_mode() -> None:
    schema = JsonSchemaDocument(schema_json='{"type":"object"}')
    tool = ModelTool(name="candidate", description="Supplied schema", parameters=schema)
    registry, current_recipe = supported(), recipe()
    with pytest.raises(ValueError):
        FullContextInputEstimator(registry, current_recipe).estimate(
            request(
                bounds=bounds(), data_classification="public", tools=(tool,), output_schema=None
            ),
            registry,
            current_recipe,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"input_text": "Another public input"},
        {"system_text": "Another public instruction"},
        {"request_id": UUID(int=101)},
        {"output_schema": JsonSchemaDocument(schema_json='{"type":"object"}')},
    ],
)
def test_retained_estimate_cannot_be_spliced_into_a_changed_request(
    change: dict[str, object],
) -> None:
    registry, current_recipe = supported(), recipe()
    original = request(bounds=bounds(), data_classification="public")
    result = FullContextInputEstimator(registry, current_recipe).estimate(
        original, registry, current_recipe
    )
    changed = type(original).model_validate(original.model_dump(by_alias=True) | change)
    with pytest.raises(ValueError):
        require_input_estimate(changed, result, current_recipe)


def test_whole_proof_cannot_mix_components_or_represent_a_legacy_bound() -> None:
    registry, current_recipe = supported(), recipe()
    call = request(bounds=bounds(), data_classification="public")
    result = FullContextInputEstimator(registry, current_recipe).estimate(
        call, registry, current_recipe
    )
    with pytest.raises(ValueError):
        InputEstimate.model_validate(result.model_dump() | {"sdk_overhead_tokens": 1})
    legacy = type(call).model_validate(
        call.model_dump(by_alias=True)
        | {"bounds": call.bounds.model_dump(exclude={"input_bound_kind"})}
    )
    adjusted = InputEstimate.model_validate(
        result.model_dump() | {"request_hash": request_hash(legacy)}
    )
    with pytest.raises(ValueError):
        require_input_estimate(legacy, adjusted, current_recipe)


def test_estimate_has_no_filesystem_version_or_provider_io(monkeypatch: pytest.MonkeyPatch) -> None:
    registry, current_recipe = supported(), recipe()
    estimator = FullContextInputEstimator(registry, current_recipe)

    def forbidden() -> str:
        raise AssertionError("Pure estimation attempted constructor IO")

    monkeypatch.setattr(estimator_module, "input_conformance_reference", forbidden)
    result = estimator.estimate(
        request(bounds=bounds(), data_classification="public"), registry, current_recipe
    )
    assert result.total_tokens == 400_000
    with pytest.raises(FrozenInstanceError):
        estimator.__setattr__("_conformance", "replacement")


def test_changed_actual_sdk_version_or_source_cannot_mint_conformance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(estimator_module, "version", lambda _: "unreviewed")
    with pytest.raises(ValueError):
        input_conformance_reference()
    file = tmp_path / "supplied-sdk.py"
    file.write_text("modified framing")
    with pytest.raises(ValueError):
        estimator_module._source_hash(file, "0" * 64)
