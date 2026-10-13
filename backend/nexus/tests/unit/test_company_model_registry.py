"""Policy-preserving evaluated routing with synthetic provider registrations."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.core.llm.company_pricing import PriceCard, TokenBounds
from nexus.core.llm.company_registry import (
    EvaluationEvidence,
    ModelHealth,
    ModelRegistration,
    ModelRegistry,
)
from nexus.core.llm.company_routing import ModelPolicy, RoutingDeniedError, route_models

NOW = datetime(2026, 10, 13, 10, tzinfo=UTC)
COMPANY = UUID(int=1)


def model(registry_id: str = "fixture-a", /, **updates: object) -> ModelRegistration:
    """Return a synthetic evaluated model; no provider client is constructed."""
    data: dict[str, object] = {
        "registry_id": registry_id,
        "provider": "openai",
        "model_id": registry_id,
        "endpoint_id": "fixture-endpoint",
        "api_family": "openai_responses",
        "enabled": True,
        "capabilities": frozenset({"text", "tools", "structured_output", "code", "reasoning"}),
        "allowed_data": frozenset({"internal"}),
        "context_window": 10000,
        "max_output_tokens": 2000,
        "fallback_priority": 10,
        "health": ModelHealth(
            status="healthy",
            checked_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(minutes=5),
        ),
        "evaluations": (
            EvaluationEvidence(
                profile="engineering",
                suite_version="frozen-1",
                artifact_reference="fixture:conformance",
                score=Decimal("0.95"),
                conformance_passed=True,
                evaluated_at=NOW - timedelta(days=1),
                expires_at=NOW + timedelta(days=1),
            ),
        ),
        "price": PriceCard(
            version="prices-1",
            as_of=NOW.date(),
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=1),
            source_reference="fixture:prices",
            input_per_million=Decimal("2"),
            output_per_million=Decimal("8"),
            reasoning_semantics="included_in_output",
        ),
    }
    return ModelRegistration.model_validate(data | updates)


def policy(**updates: object) -> ModelPolicy:
    """Return explicit frozen authority and available monetary allowance."""
    data: dict[str, object] = {
        "company_id": COMPANY,
        "task_id": UUID(int=2),
        "trace_id": UUID(int=3),
        "policy_version": "policy-1",
        "pricebook_version": "prices-1",
        "profile": "engineering",
        "allowed_models": frozenset({"fixture-a", "fixture-b", "fixture-c", "fixture-d"}),
        "allowed_providers": frozenset({"openai", "google", "openai_compatible"}),
        "allowed_api_families": frozenset(
            {"openai_responses", "google_generate_content", "openai_chat"}
        ),
        "data_classification": "internal",
        "minimum_score": Decimal("0.80"),
        "evaluation_suite_version": "frozen-1",
        "available_usd": Decimal("0.030000"),
        "token_bounds": TokenBounds(input_tokens=1000, max_output_tokens=500),
        "remaining_model_requests": 12,
    }
    return ModelPolicy.model_validate(data | updates)


def registry(*models: ModelRegistration, **updates: object) -> ModelRegistry:
    return ModelRegistry.model_validate(
        {
            "company_id": COMPANY,
            "revision": "registry-1",
            "pricebook_version": "prices-1",
            "models": models,
        }
        | updates
    )


def test_cheapest_eligible_model_wins_and_fallbacks_are_bounded() -> None:
    expensive = model("fixture-a")
    assert expensive.price is not None
    cheap = model(
        "fixture-b",
        provider="google",
        api_family="google_generate_content",
        price=expensive.price.model_copy(update={"output_per_million": Decimal("4")}),
    )
    plan = route_models(
        registry(expensive, model("fixture-d"), cheap, model("fixture-c")), policy(), now=NOW
    )
    assert plan.primary.model.registry_id == "fixture-b"
    assert len(plan.fallbacks) == 2
    assert plan.reservation_usd == Decimal("0.016000")
    assert plan.task_id == UUID(int=2)
    assert plan.policy_version == "policy-1"


def test_routing_is_stable_across_catalog_order_and_priority_ties() -> None:
    a, b, c = (
        model(),
        model("fixture-b", fallback_priority=2),
        model("fixture-c", fallback_priority=2),
    )
    first = route_models(registry(a, c, b), policy(), now=NOW)
    second = route_models(registry(b, a, c), policy(), now=NOW)
    assert first == second
    assert first.primary.model.registry_id == "fixture-b"
    assert [item.model.registry_id for item in first.fallbacks] == ["fixture-c", "fixture-a"]


def test_fallback_costs_share_the_original_remaining_budget() -> None:
    plan = route_models(
        registry(model(), model("fixture-b"), model("fixture-c")),
        policy(available_usd=Decimal("0.011999")),
        now=NOW,
    )
    assert plan.primary.quote.amount_usd == Decimal("0.006000")
    assert plan.fallbacks == ()
    assert plan.reservation_usd == Decimal("0.006000")


def test_fallbacks_cannot_reset_remaining_request_count() -> None:
    plan = route_models(
        registry(model(), model("fixture-b")), policy(remaining_model_requests=1), now=NOW
    )
    assert plan.fallbacks == ()
    with pytest.raises(RoutingDeniedError):
        route_models(registry(model()), policy(remaining_model_requests=0), now=NOW)


@pytest.mark.parametrize(
    "updates",
    [
        {"allowed_models": frozenset()},
        {"allowed_providers": frozenset({"google"})},
        {"allowed_api_families": frozenset({"openai_chat"})},
        {"data_classification": "confidential"},
        {"evaluation_suite_version": "different-suite"},
        {"minimum_score": Decimal("0.96")},
        {"available_usd": Decimal("0.005999")},
        {"pricebook_version": "new-prices"},
        {"company_id": UUID(int=99)},
        {"token_bounds": TokenBounds(input_tokens=9501, max_output_tokens=500)},
        {"token_bounds": TokenBounds(input_tokens=100, max_output_tokens=2001)},
    ],
)
def test_policy_or_capacity_denial_has_no_unrestricted_fallback(updates: dict[str, object]) -> None:
    with pytest.raises(RoutingDeniedError):
        route_models(registry(model()), policy(**updates), now=NOW)


@pytest.mark.parametrize(
    "updates",
    [
        {"enabled": False},
        {"capabilities": frozenset({"text", "tools"})},
        {"price": None},
        {
            "health": ModelHealth(
                status="unknown", checked_at=NOW, expires_at=NOW + timedelta(minutes=1)
            )
        },
        {
            "health": ModelHealth(
                status="healthy", checked_at=NOW - timedelta(hours=1), expires_at=NOW
            )
        },
        {"evaluations": ()},
    ],
)
def test_unregistered_unhealthy_unevaluated_or_unpriced_models_are_not_selected(
    updates: dict[str, object],
) -> None:
    with pytest.raises(RoutingDeniedError):
        route_models(registry(model(**updates)), policy(), now=NOW)


def test_expired_future_or_failed_evaluation_is_rejected() -> None:
    baseline = model()
    for change in (
        {"expires_at": NOW},
        {"evaluated_at": NOW + timedelta(seconds=1)},
        {"conformance_passed": False},
    ):
        evaluation = baseline.evaluations[0].model_copy(update=change)
        with pytest.raises(RoutingDeniedError):
            route_models(registry(model(evaluations=(evaluation,))), policy(), now=NOW)


def test_more_than_two_fallbacks_and_unknown_capabilities_are_schema_errors() -> None:
    with pytest.raises(ValidationError):
        policy(max_fallbacks=3)
    with pytest.raises(ValidationError):
        model(capabilities=frozenset({"magic"}))
    with pytest.raises(ValidationError):
        policy(available_usd=Decimal("Infinity"))


@pytest.mark.parametrize(
    "updates",
    [
        {"provider": "google", "api_family": "openai_responses"},
        {"provider": "openai_compatible", "api_family": "google_generate_content"},
        {"context_window": True},
        {"max_output_tokens": -1},
        {"allowed_data": frozenset({"secrets"})},
        {"capabilities": frozenset({"embeddings"})},
    ],
)
def test_inconsistent_registration_is_rejected(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model(**updates)


def test_duplicate_ids_endpoints_and_pricebook_mismatch_are_rejected() -> None:
    with pytest.raises(ValidationError):
        registry(model(), model())
    with pytest.raises(ValidationError):
        registry(model(), model("fixture-b", model_id="fixture-a"))
    with pytest.raises(ValidationError):
        registry(model(), pricebook_version="not-prices-1")


def test_empty_catalog_has_no_automatic_provider_seed() -> None:
    with pytest.raises(RoutingDeniedError):
        route_models(registry(), policy(), now=NOW)


def test_catalog_policy_and_route_wire_roundtrips() -> None:
    catalog, request = registry(model()), policy()
    assert ModelRegistry.model_validate_json(catalog.model_dump_json()) == catalog
    assert ModelPolicy.model_validate_json(request.model_dump_json()) == request
    plan = route_models(catalog, request, now=NOW)
    assert plan.model_validate_json(plan.model_dump_json()) == plan


def test_fallback_cannot_bypass_data_policy_or_evaluation_threshold() -> None:
    bad_data = model("fixture-b", allowed_data=frozenset({"public"}))
    failed_eval = model(
        "fixture-c",
        evaluations=(model().evaluations[0].model_copy(update={"score": Decimal("0.20")}),),
    )
    plan = route_models(registry(model(), bad_data, failed_eval), policy(), now=NOW)
    assert plan.primary.model.registry_id == "fixture-a"
    assert plan.fallbacks == ()


def test_future_health_and_unsupported_reasoning_price_never_enter_routing() -> None:
    bad_health = model(
        health=ModelHealth(
            status="healthy",
            checked_at=NOW + timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=2),
        )
    )
    prices = model().price
    assert prices is not None
    no_reasoning = model(price=prices.model_copy(update={"reasoning_semantics": "none"}))
    for candidate in (bad_health, no_reasoning):
        with pytest.raises(RoutingDeniedError):
            route_models(registry(candidate), policy(), now=NOW)


def test_input_only_embedding_profile_requires_dimension_and_output_zero() -> None:
    baseline = model()
    assert baseline.price is not None
    embedding = model(
        capabilities=frozenset({"embeddings"}),
        api_family="openai_embeddings",
        embedding_dimension=768,
        max_output_tokens=0,
        price=baseline.price.model_copy(
            update={"output_per_million": Decimal(0), "reasoning_semantics": "none"}
        ),
        evaluations=(baseline.evaluations[0].model_copy(update={"profile": "embeddings"}),),
    )
    request = policy(
        profile="embeddings",
        allowed_api_families=frozenset({"openai_embeddings"}),
        token_bounds=TokenBounds(input_tokens=1000, max_output_tokens=0),
    )
    assert route_models(registry(embedding), request, now=NOW).reservation_usd == Decimal(
        "0.002000"
    )
    with pytest.raises(RoutingDeniedError):
        route_models(
            registry(embedding),
            request.model_copy(
                update={"token_bounds": TokenBounds(input_tokens=1000, max_output_tokens=1)}
            ),
            now=NOW,
        )


def test_schema_versions_unknown_provider_and_duplicate_evaluations_are_denied() -> None:
    for updates in (
        {"provider": "undiscovered"},
        {"schema_version": "unknown"},
        {"evaluations": (model().evaluations[0], model().evaluations[0])},
    ):
        with pytest.raises(ValidationError):
            model(**updates)


def test_routing_revalidates_copy_bypass_and_timezone() -> None:
    for request in (
        policy().model_copy(update={"max_fallbacks": 9}),
        policy().model_copy(update={"remaining_model_requests": -1}),
    ):
        with pytest.raises(RoutingDeniedError):
            route_models(registry(model()), request, now=NOW)
    with pytest.raises(RoutingDeniedError):
        route_models(registry(model()), policy(), now=NOW.replace(tzinfo=None))
