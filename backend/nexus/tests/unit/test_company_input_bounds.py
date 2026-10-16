"""Explicit financial ceilings; supplied registrations are not live qualification."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import httpx2
import pytest
from pydantic import ValidationError

from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.core.llm.company_adapters import CompanyModelAdapters
from nexus.core.llm.company_pricing import TokenBounds
from nexus.core.llm.company_registry import ModelRegistry
from nexus.core.llm.company_routing import RoutingDeniedError, route_models
from nexus.tests.unit.test_company_model_registry import policy
from nexus.tests.unit.test_company_provider_conformance import (
    KEY,
    NOW,
    Authorizer,
    EndpointResolver,
    catalog,
    request,
    response,
)


def supported(provider: str = "openai") -> ModelRegistry:
    """Real model identifiers with explicitly supplied health/evaluation/price data."""
    original = catalog(provider)
    ceiling, output, name = (
        (400_000, 128_000, "gpt-5.4-mini-2026-03-17")
        if provider == "openai"
        else (1_048_576, 65_536, "gemini-3.5-flash-lite")
    )
    row = original.models[0].model_dump() | {
        "model_id": name,
        "context_window": ceiling,
        "max_output_tokens": output,
        "allowed_data": frozenset({"public"}),
        "evaluations": tuple(
            value.model_dump()
            | {
                "evaluated_at": NOW - timedelta(hours=1),
                "expires_at": NOW + timedelta(hours=1),
            }
            for value in original.models[0].evaluations
        ),
    }
    return ModelRegistry.model_validate(original.model_dump() | {"models": (row,)})


def bounds(provider: str = "openai", **updates: object) -> TokenBounds:
    return TokenBounds.model_validate(
        {
            "input_tokens": 400_000 if provider == "openai" else 1_048_576,
            "max_output_tokens": 512,
            "input_bound_kind": "model_input_ceiling_v1",
        }
        | updates
    )


def test_default_bound_wire_is_exact_and_optional_none_is_absent() -> None:
    expected = (
        '{"schema_version":"nexus.company.models.v1","input_tokens":1000,'
        '"max_output_tokens":64,"unit":"text_tokens",'
        '"output_cap_semantics":"total_including_reasoning"}'
    )
    assert TokenBounds(input_tokens=1000, max_output_tokens=64).model_dump_json() == expected


@pytest.mark.parametrize("provider", ["openai", "google"])
def test_whole_ceiling_is_explicit_cost_reservation_not_combined_fit(provider: str) -> None:
    catalog_value = supported(provider)
    selected = route_models(
        catalog_value,
        policy(
            token_bounds=bounds(provider),
            data_classification="public",
            available_usd=Decimal("5"),
            max_fallbacks=0,
        ),
        now=NOW,
    )
    assert selected.primary.model == catalog_value.models[0]
    assert selected.primary.quote.amount_usd > Decimal("0.8")
    legacy = bounds(provider).model_dump(exclude={"input_bound_kind"})
    with pytest.raises(RoutingDeniedError):
        route_models(
            catalog_value,
            policy(token_bounds=legacy, data_classification="public", available_usd="5"),
            now=NOW,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"model_id": "gpt-5.4-mini"},
        {"model_id": "unknown"},
        {"api_family": "openai_chat"},
        {"context_window": 400_001},
        {"max_output_tokens": 128_001},
    ],
)
def test_cost_ceiling_cannot_enter_an_unreviewed_binding(change: dict[str, object]) -> None:
    from nexus.core.llm.company_input_bounds import require_model_input_bounds

    row = supported().models[0]
    changed = type(row).model_validate(row.model_dump() | change)
    with pytest.raises(ValueError):
        require_model_input_bounds(changed, bounds())


@pytest.mark.parametrize("input_tokens", [399_488, 399_999, 400_001])
def test_ceiling_never_subtracts_output_or_accepts_caller_ceiling(input_tokens: int) -> None:
    from nexus.core.llm.company_input_bounds import require_model_input_bounds

    with pytest.raises(ValueError):
        require_model_input_bounds(supported().models[0], bounds(input_tokens=input_tokens))


@pytest.mark.parametrize("cap", [0, 128_001])
def test_ceiling_rejects_empty_or_excess_output(cap: int) -> None:
    from nexus.core.llm.company_input_bounds import require_model_input_bounds

    with pytest.raises(ValueError):
        require_model_input_bounds(supported().models[0], bounds(max_output_tokens=cap))


@pytest.mark.parametrize("provider,output", [("openai", 128_000), ("google", 65_536)])
def test_documented_output_ceiling_is_distinct_from_local_policy(
    provider: str, output: int
) -> None:
    from nexus.core.llm.company_input_bounds import model_output_ceiling, require_model_input_bounds

    original = supported(provider).models[0]
    narrowed = type(original).model_validate(original.model_dump() | {"max_output_tokens": 512})
    assert model_output_ceiling(narrowed) == output
    require_model_input_bounds(narrowed, bounds(provider))
    with pytest.raises(ValueError):
        require_model_input_bounds(narrowed, bounds(provider, max_output_tokens=513))


@pytest.mark.parametrize("denial", ["disabled", "health", "evaluation", "price", "budget", "data"])
def test_financial_mode_never_bypasses_ordinary_eligibility(denial: str) -> None:
    original = supported()
    row = original.models[0]
    changes: dict[str, object] = {}
    if denial == "disabled":
        changes["enabled"] = False
    elif denial == "health":
        changes["health"] = row.health.model_dump() | {"status": "unknown"}
    elif denial == "evaluation":
        changes["evaluations"] = ()
    elif denial == "price":
        changes["price"] = None
    current = ModelRegistry.model_validate(
        original.model_dump() | {"models": (row.model_dump() | changes,)}
    )
    with pytest.raises(RoutingDeniedError):
        route_models(
            current,
            policy(
                token_bounds=bounds(),
                max_fallbacks=0,
                data_classification="internal" if denial == "data" else "public",
                available_usd="0.05" if denial == "budget" else "5",
            ),
            now=NOW,
        )


@pytest.mark.parametrize("kind", [True, "component_count", "latest"])
def test_unknown_bound_kinds_are_not_modes(kind: object) -> None:
    with pytest.raises(ValidationError):
        bounds(input_bound_kind=kind)


@pytest.mark.parametrize("provider", ["openai", "google"])
@pytest.mark.parametrize("classification", ["public", "internal"])
async def test_actual_sdk_keeps_native_schema_cap_and_one_post(
    provider: str, classification: str
) -> None:
    from pydantic import SecretStr

    actual = supported(provider)
    actual = ModelRegistry.model_validate(
        actual.model_dump()
        | {
            "models": (
                actual.models[0].model_dump() | {"allowed_data": frozenset({"public", "internal"})},
            )
        }
    )
    calls: list[dict[str, object]] = []

    def wire(value: httpx2.Request) -> httpx2.Response:
        calls.append(json.loads(value.content))
        payload = response(provider)
        payload["model" if provider == "openai" else "modelVersion"] = actual.models[0].model_id
        return httpx2.Response(200, json=payload)

    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider=provider,
        api_family=actual.models[0].api_family,
        base_url="https://offline.invalid/v1"
        if provider == "openai"
        else "https://offline.invalid",
        api_key=SecretStr(KEY),
        transport=httpx2.MockTransport(wire),
    )
    authorizer = Authorizer()
    result = await CompanyModelAdapters(
        actual, EndpointResolver(endpoint), authorizer
    ).request_once(request(bounds=bounds(provider), data_classification=classification), now=NOW)
    assert result.status == "response" and result.billing == "known"
    assert len(calls) == authorizer.claims == 1
    if provider == "openai":
        assert calls[0]["max_output_tokens"] == 512
        assert "json_schema" in json.dumps(calls[0]["text"])
    else:
        assert "512" in json.dumps(calls[0]["generationConfig"])
        assert "responseJsonSchema" in json.dumps(calls[0]["generationConfig"])


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_disallowed_internal_request_never_claims_or_reaches_sdk(provider: str) -> None:
    from pydantic import SecretStr

    def forbidden(_: httpx2.Request) -> httpx2.Response:
        raise AssertionError("Disallowed classification reached provider transport")

    actual = supported(provider)  # Its existing public-only policy is unchanged.
    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider=provider,
        api_family=actual.models[0].api_family,
        base_url="https://offline.invalid",
        api_key=SecretStr(KEY),
        transport=httpx2.MockTransport(forbidden),
    )
    authorizer = Authorizer()
    result = await CompanyModelAdapters(
        actual, EndpointResolver(endpoint), authorizer
    ).request_once(request(bounds=bounds(provider), data_classification="internal"), now=NOW)
    assert result.status == "denied" and result.billing == "not_issued"
    assert authorizer.claims == 0
