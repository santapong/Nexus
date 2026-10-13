"""Explicit evaluated model catalog; registering a model never creates a client."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from nexus.company.contracts.base import Name
from nexus.core.llm.company_pricing import ModelContract, PriceCard, Score, Tokens

Provider = Literal["openai", "google", "openai_compatible", "test"]
ApiFamily = Literal[
    "openai_responses",
    "openai_chat",
    "google_generate_content",
    "openai_embeddings",
    "google_embeddings",
    "test",
]
Capability = Literal["text", "structured_output", "tools", "code", "reasoning", "embeddings"]
DataClassification = Literal["public", "internal", "confidential", "restricted"]
Profile = Literal["reasoning", "engineering", "routine", "verification", "embeddings"]
PositiveLimit = Annotated[int, Field(gt=0, le=1_000_000_000, strict=True)]
Priority = Annotated[int, Field(ge=0, le=1_000_000, strict=True)]
_PROVIDER_APIS: dict[Provider, frozenset[ApiFamily]] = {
    "openai": frozenset({"openai_responses", "openai_chat", "openai_embeddings"}),
    "google": frozenset({"google_generate_content", "google_embeddings"}),
    "openai_compatible": frozenset({"openai_chat", "openai_embeddings"}),
    "test": frozenset({"test"}),
}


class EvaluationEvidence(ModelContract):
    """Versioned frozen evaluation and adapter conformance result for one profile."""

    profile: Profile
    suite_version: Name
    artifact_reference: Name
    score: Score
    conformance_passed: bool
    evaluated_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator("score", mode="before")
    @classmethod
    def reject_inexact_score(cls, value: object) -> object:
        """Keep threshold comparisons exact and reject boolean/float scores."""
        if isinstance(value, (float, bool)):
            raise ValueError("score must use Decimal or an exact decimal string")
        return value

    @model_validator(mode="after")
    def require_positive_validity(self) -> Self:
        """Do not allow an evaluation with a contradictory validity interval."""
        if self.expires_at <= self.evaluated_at:
            raise ValueError("evaluation expiry must follow evaluation time")
        return self


class ModelHealth(ModelContract):
    """A short-lived health observation, not an infinite availability promise."""

    status: Literal["healthy", "unhealthy", "unknown"] = "unknown"
    checked_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def require_positive_validity(self) -> Self:
        """Prevent stale or contradictory health windows from being registered."""
        if self.expires_at <= self.checked_at:
            raise ValueError("health expiry must follow observation time")
        return self


class ModelRegistration(ModelContract):
    """Exact endpoint/model/API/capabilities; disabled until explicitly configured."""

    registry_id: Name
    provider: Provider
    model_id: Name
    endpoint_id: Name
    api_family: ApiFamily
    enabled: bool = False
    capabilities: frozenset[Capability]
    allowed_data: frozenset[DataClassification]
    context_window: PositiveLimit
    max_output_tokens: Tokens
    embedding_dimension: PositiveLimit | None = None
    fallback_priority: Priority = 0
    health: ModelHealth
    evaluations: tuple[EvaluationEvidence, ...] = ()
    price: PriceCard | None = None

    @model_validator(mode="after")
    def require_consistent_model(self) -> Self:
        """Reject incompatible API declarations and ambiguous embedding shapes."""
        if self.api_family not in _PROVIDER_APIS[self.provider]:
            raise ValueError("provider and API family are incompatible")
        if self.max_output_tokens > self.context_window:
            raise ValueError("output limit exceeds context window")
        embeddings = "embeddings" in self.capabilities
        if (embeddings and self.max_output_tokens != 0) or (
            not embeddings and self.max_output_tokens == 0
        ):
            raise ValueError("output limit must be zero for embeddings and positive for generation")
        if embeddings != (self.embedding_dimension is not None):
            raise ValueError("embedding capability requires an explicit dimension")
        if self.api_family.endswith("embeddings") != embeddings and self.provider != "test":
            raise ValueError("embedding capability and API family must agree")
        profiles = [evaluation.profile for evaluation in self.evaluations]
        if len(profiles) != len(set(profiles)):
            raise ValueError("one evaluation per profile is required")
        return self


class ModelRegistry(ModelContract):
    """Company-scoped immutable catalog with no implicit models or discovery."""

    company_id: UUID
    revision: Name
    pricebook_version: Name
    models: tuple[ModelRegistration, ...] = ()

    @model_validator(mode="after")
    def require_unique_bindings(self) -> Self:
        """Avoid aliases bypassing fallback counts and reject mixed pricebooks."""
        ids = [model.registry_id for model in self.models]
        endpoints = [
            (model.provider, model.endpoint_id, model.api_family, model.model_id)
            for model in self.models
        ]
        if len(ids) != len(set(ids)) or len(endpoints) != len(set(endpoints)):
            raise ValueError("duplicate registry ID or exact provider/model/API binding")
        if any(
            model.price and model.price.version != self.pricebook_version for model in self.models
        ):
            raise ValueError("model price does not belong to registry pricebook")
        return self
