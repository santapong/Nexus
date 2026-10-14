"""Explicit current eligibility observations pin an unchanged immutable model row."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.management.base import SHA256, ManagementContract, Name
from nexus.company.management.canonical import canonical_sha256
from nexus.core.llm.company_registry import (
    EvaluationEvidence,
    ModelHealth,
    ModelRegistration,
    ModelRegistry,
)


class ModelEligibilityObservation(ManagementContract):
    """Trusted dated configuration, never a provider check, approval or call permit."""

    observation_id: UUID
    registry_revision: Name
    registry_id: Name
    registration_sha256: SHA256
    receipt_sha256: SHA256
    health: ModelHealth
    evaluations: tuple[EvaluationEvidence, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def unique_profiles(self) -> Self:
        """One unambiguous replacement evaluation per original profile."""
        if len({row.profile for row in self.evaluations}) != len(self.evaluations):
            raise ValueError("Current observations require unique evaluation profiles")
        return self


def validate_model_observations(
    registry: ModelRegistry, observations: tuple[ModelEligibilityObservation, ...]
) -> None:
    """Reject unknown, duplicate or mismatched pins before catalog use."""
    if len(observations) > 32:
        raise ValueError("Current model observations exceed their configured bound")
    if len({row.registry_id for row in observations}) != len(observations):
        raise ValueError("Current observations require unique exact model IDs")
    if len({row.observation_id for row in observations}) != len(observations):
        raise ValueError("Current observations require unique observation IDs")
    registered = {row.registry_id: row for row in registry.models}
    for row in observations:
        original = registered.get(row.registry_id)
        if (
            original is None
            or row.company_id != registry.company_id
            or row.registry_revision != registry.revision
            or row.registration_sha256 != canonical_sha256(original)
            or not {value.profile for value in row.evaluations}
            <= {value.profile for value in original.evaluations}
        ):
            raise ValueError("Current model observation differs from its immutable registration")


def effective_model_registration(
    registry: ModelRegistry,
    observations: tuple[ModelEligibilityObservation, ...],
    model: ModelRegistration,
) -> ModelRegistration:
    """Resolve only health/evaluation; all model identity and pricing fields stay exact."""
    validate_model_observations(registry, observations)
    observation = next((row for row in observations if row.registry_id == model.registry_id), None)
    if observation is None:
        return model
    if canonical_sha256(model) != observation.registration_sha256:
        raise ValueError("Current observation cannot replace a changed registration")
    return ModelRegistration.model_validate(
        model.model_dump() | {"health": observation.health, "evaluations": observation.evaluations}
    )
