"""Dated eligibility narrows unchanged registrations; decoded provenance grants no permit."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from nexus.company.management.base import SHA256
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.model_observations import (
    ModelEligibilityObservation,
    validate_model_observations,
)
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_pricing import CostQuote, ModelContract
from nexus.core.llm.company_registry import ModelRegistration, ModelRegistry


class ModelEligibilityProvenance(ModelContract):
    """Original/current observation pins, retained as evidence after their execution window."""

    registration_sha256: SHA256
    observation_sha256: SHA256
    observation: ModelEligibilityObservation

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)

    def require_binding(
        self, original: ModelRegistration, company_id: UUID, registry_revision: str
    ) -> None:
        observed = self.observation
        if (
            self.registration_sha256 != canonical_sha256(original)
            or self.observation_sha256 != canonical_sha256(observed)
            or (observed.company_id, observed.registry_revision, observed.registry_id)
            != (company_id, registry_revision, original.registry_id)
            or observed.registration_sha256 != self.registration_sha256
            or not {value.profile for value in observed.evaluations}
            <= {value.profile for value in original.evaluations}
        ):
            raise ValueError("Model eligibility provenance differs from original registration")


class BeforeModelSdk(Protocol):
    """Trusted actual committed-intent revalidation; a returned clock is not a portable permit."""

    async def __call__(
        self, request: CompanyModelRequest, quote: CostQuote, eligibility_sha256: str | None
    ) -> datetime: ...


def validated_observations(
    registry: ModelRegistry, observations: tuple[ModelEligibilityObservation, ...]
) -> tuple[ModelEligibilityObservation, ...]:
    """Copy trusted constructor input and validate the complete bounded tuple before selection."""
    copied = tuple(
        ModelEligibilityObservation.model_validate_json(item.model_dump_json())
        for item in observations
    )
    validate_model_observations(registry, copied)
    return copied


def eligibility_provenance(
    registry: ModelRegistry,
    observations: tuple[ModelEligibilityObservation, ...],
    original: ModelRegistration,
) -> ModelEligibilityProvenance | None:
    """No current observation is distinct from an original registration's dated evidence."""
    validate_model_observations(registry, observations)
    selected = next(
        (item for item in observations if item.registry_id == original.registry_id), None
    )
    if selected is None:
        return None
    result = ModelEligibilityProvenance(
        registration_sha256=canonical_sha256(original),
        observation_sha256=canonical_sha256(selected),
        observation=selected,
    )
    result.require_binding(original, registry.company_id, registry.revision)
    return result
