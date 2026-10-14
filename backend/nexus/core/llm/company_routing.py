"""Deterministic policy-preserving route plans, without reserving or invoking I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from nexus.company.contracts.base import USD, Name
from nexus.company.management.model_observations import (
    ModelEligibilityObservation,
    effective_model_registration,
)
from nexus.core.llm.company_eligibility import validated_observations
from nexus.core.llm.company_pricing import (
    CostQuote,
    ModelContract,
    PricingDeniedError,
    Score,
    TokenBounds,
    quote_cost,
)
from nexus.core.llm.company_registry import (
    ApiFamily,
    Capability,
    DataClassification,
    ModelRegistration,
    ModelRegistry,
    Profile,
    Provider,
)

_PROFILE_CAPABILITIES: dict[Profile, frozenset[Capability]] = {
    "reasoning": frozenset({"reasoning", "structured_output"}),
    "engineering": frozenset({"code", "tools", "structured_output"}),
    "routine": frozenset({"text"}),
    "verification": frozenset({"reasoning", "structured_output"}),
    "embeddings": frozenset({"embeddings"}),
}


class RoutingDeniedError(ValueError):
    """No allowed evaluated current-price route fits the original scope/limits."""


class ModelPolicy(ModelContract):
    """Trusted current policy and remaining allowance from the persistent journal.

    available_usd must be the lesser available company/day/work/parent allowance.
    Token bounds are for one call, never the whole multi-call agent execution.
    A route plan is a proposal; reserve atomically before calling and refresh
    policy, health and billing versions at each consequential boundary.
    """

    company_id: UUID
    task_id: UUID
    trace_id: UUID
    policy_version: Name
    pricebook_version: Name
    profile: Profile
    allowed_models: frozenset[Name]
    allowed_providers: frozenset[Provider]
    allowed_api_families: frozenset[ApiFamily]
    data_classification: DataClassification
    required_capabilities: frozenset[Capability] = frozenset()
    minimum_score: Score
    evaluation_suite_version: Name
    available_usd: USD
    token_bounds: TokenBounds
    max_fallbacks: Annotated[int, Field(ge=0, le=2, strict=True)] = 2
    remaining_model_requests: Annotated[int, Field(ge=0, le=12, strict=True)]

    @field_validator("minimum_score", "available_usd", mode="before")
    @classmethod
    def require_exact_money_and_score(cls, value: object) -> object:
        """Do not let float rounding or booleans weaken a budget/quality gate."""
        if isinstance(value, (float, bool)):
            raise ValueError("budget and score must use exact decimals")
        return value


class RoutedModel(ModelContract):
    """An eligible model and its exact price-bound single-call quotation."""

    model: ModelRegistration
    quote: CostQuote
    eligibility: tuple[Name, ...] = (
        "allowlisted",
        "data_policy",
        "capabilities",
        "evaluated",
        "healthy",
        "priced",
        "budget",
    )


class RoutingPlan(ModelContract):
    """A bounded ordered chain preserving original identity and budget lineage."""

    company_id: UUID
    task_id: UUID
    trace_id: UUID
    policy_version: Name
    pricebook_version: Name
    registry_revision: Name
    primary: RoutedModel
    fallbacks: tuple[RoutedModel, ...] = Field(max_length=2)
    reservation_usd: USD


def _eligible(model: ModelRegistration, policy: ModelPolicy, now: datetime) -> bool:
    required = policy.required_capabilities | _PROFILE_CAPABILITIES[policy.profile]
    if (
        not model.enabled
        or model.registry_id not in policy.allowed_models
        or model.provider not in policy.allowed_providers
        or model.api_family not in policy.allowed_api_families
        or policy.data_classification not in model.allowed_data
        or not required <= model.capabilities
    ):
        return False
    bounds = policy.token_bounds
    if (
        bounds.input_tokens + bounds.max_output_tokens > model.context_window
        or bounds.max_output_tokens > model.max_output_tokens
        or (policy.profile == "embeddings" and bounds.max_output_tokens != 0)
    ):
        return False
    health = model.health
    if health.status != "healthy" or not health.checked_at <= now < health.expires_at:
        return False
    return any(
        e.profile == policy.profile
        and e.suite_version == policy.evaluation_suite_version
        and e.conformance_passed
        and e.score >= policy.minimum_score
        and e.evaluated_at <= now < e.expires_at
        for e in model.evaluations
    )


def _candidates(
    registry: ModelRegistry,
    policy: ModelPolicy,
    now: datetime,
    observations: tuple[ModelEligibilityObservation, ...],
) -> list[RoutedModel]:
    candidates: list[RoutedModel] = []
    for original in registry.models:
        model = effective_model_registration(registry, observations, original)
        if not _eligible(model, policy, now):
            continue
        try:
            quote = quote_cost(model.price, policy.token_bounds, now=now)
        except PricingDeniedError:
            continue  # An ineligible price cannot enter either primary or fallback.
        if (
            "reasoning" in model.capabilities
            and model.price is not None
            and model.price.reasoning_semantics != "included_in_output"
        ):
            continue
        if quote.amount_usd <= policy.available_usd:
            candidates.append(RoutedModel(model=model, quote=quote))
    return sorted(
        candidates,
        key=lambda item: (
            item.quote.amount_usd,
            item.model.fallback_priority,
            item.model.registry_id,
        ),
    )


def route_models(
    registry: ModelRegistry,
    policy: ModelPolicy,
    *,
    now: datetime,
    model_observations: tuple[ModelEligibilityObservation, ...] = (),
) -> RoutingPlan:
    """Choose cheapest eligible primary and at most two affordable alternatives.

    Sum all attempted-call upper bounds conservatively: a billable failed primary
    never frees its allowance for a fallback. This is pure selection, not a cost
    reservation or execution permit. No newly released models are auto-adopted.
    """
    try:
        registry = ModelRegistry.model_validate(registry.model_dump())
        policy = ModelPolicy.model_validate(policy.model_dump())
        model_observations = validated_observations(registry, model_observations)
    except ValueError as exc:
        raise RoutingDeniedError("invalid registry or policy contract") from exc
    if now.utcoffset() is None:
        raise RoutingDeniedError("routing time must be timezone-aware")
    if (
        registry.company_id != policy.company_id
        or registry.pricebook_version != policy.pricebook_version
    ):
        raise RoutingDeniedError("company or pricebook mismatch")
    if not policy.remaining_model_requests:
        raise RoutingDeniedError("logical work item request allowance exhausted")
    candidates = _candidates(registry, policy, now, model_observations)
    if not candidates:
        raise RoutingDeniedError("no eligible model fits current policy, price and budget")
    selected, total = [candidates[0]], candidates[0].quote.amount_usd
    limit = min(1 + policy.max_fallbacks, policy.remaining_model_requests)
    for candidate in candidates[1:]:
        if len(selected) >= limit:
            break
        if total + candidate.quote.amount_usd <= policy.available_usd:
            selected.append(candidate)
            total += candidate.quote.amount_usd
    return RoutingPlan(
        company_id=policy.company_id,
        task_id=policy.task_id,
        trace_id=policy.trace_id,
        policy_version=policy.policy_version,
        pricebook_version=policy.pricebook_version,
        registry_revision=registry.revision,
        primary=selected[0],
        fallbacks=tuple(selected[1:]),
        reservation_usd=total,
    )
