"""Measured goals preserve unknown baselines and source dates without invented scheduling."""

from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.sources import EvidenceRef
from nexus.company.management.base import (
    ManagementContract,
    Name,
    RevisionRef,
    SourceTime,
    Symbol,
    ValueContract,
    require_company,
)

MetricDecimal = Annotated[Decimal, Field(max_digits=28, decimal_places=10, allow_inf_nan=False)]


class DueIntent(ValueContract):
    source_time: SourceTime
    actionable_at: AwareDatetime | None = None
    actionable_basis: Literal["operator_explicit"] | None = None

    @model_validator(mode="after")
    def no_inference(self) -> Self:
        if (self.actionable_at is None) != (self.actionable_basis is None):
            raise ValueError("An actionable instant requires an explicit operator basis")
        return self


class KnownBaseline(ValueContract):
    kind: Literal["known"] = "known"
    value: MetricDecimal
    observed_at: SourceTime
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=32)


class UnknownBaseline(ValueContract):
    kind: Literal["unknown"] = "unknown"
    reason: Name
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)


Baseline = Annotated[KnownBaseline | UnknownBaseline, Field(discriminator="kind")]


class GoalMetric(ManagementContract):
    metric_id: Symbol
    unit: Symbol
    comparator: Literal["gt", "ge", "eq", "le", "lt"]
    target: MetricDecimal
    baseline: Baseline
    observation_recipe: Symbol | None = None

    @model_validator(mode="after")
    def evidence_scope(self) -> Self:
        require_company(self.company_id, *self.baseline.evidence)
        if len(set(self.baseline.evidence)) != len(self.baseline.evidence):
            raise ValueError("Goal baseline evidence must be exact and unique")
        return self


class GoalRevisionRef(RevisionRef):
    goal_id: UUID


class GoalDefinition(ManagementContract):
    goal_id: UUID
    title: Name
    owner_id: UUID
    mandate: RevisionRef
    metrics: tuple[GoalMetric, ...] = Field(min_length=1, max_length=8)
    due: DueIntent

    @model_validator(mode="after")
    def measured(self) -> Self:
        require_company(self.company_id, self.mandate, *self.metrics)
        if len({row.metric_id for row in self.metrics}) != len(self.metrics):
            raise ValueError("Goal metrics must have distinct identities")
        return self
