"""Immutable native measurement declarations; decoded values confer no authority."""

from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BeforeValidator, Field, model_validator

from nexus.company.brain.base import exact_count
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead, SourceRevisionRef
from nexus.company.management.base import (
    SHA256,
    ManagementContract,
    SourceTime,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import Baseline, GoalRevisionRef, MetricDecimal
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding

NATIVE_REPORT_COUNT = "native.accepted-report-count.v1"
NativeCount = Annotated[int, BeforeValidator(exact_count), Field(ge=0, le=100)]


class MetricObservationRequest(ManagementContract):
    observation_id: UUID
    goal: GoalRevisionRef
    plan: PlanRevisionRef
    metric_id: Symbol
    task_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        require_company(self.company_id, self.goal, self.plan)
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Metric task selection must be exact and unique")
        return self


class KnownMetricValue(ValueContract):
    kind: Literal["known"] = "known"
    unit: Literal["count"] = "count"
    value: NativeCount


MetricUnknownReason = Literal[
    "unsupported_recipe",
    "unsupported_unit",
    "proof_unavailable",
    "scope_unavailable",
    "versions_stale",
    "baseline_unavailable",
    "goal_inactive",
]


class UnknownMetricValue(ValueContract):
    kind: Literal["unknown"] = "unknown"
    reason: MetricUnknownReason


MetricValue = Annotated[KnownMetricValue | UnknownMetricValue, Field(discriminator="kind")]


class MetricComparison(ValueContract):
    value: MetricValue
    comparator: Literal["gt", "ge", "eq", "le", "lt"]
    target: MetricDecimal
    baseline: Baseline

    @property
    def result(self) -> Literal["satisfied", "unsatisfied", "unknown"]:
        if self.value.kind == "unknown":
            return "unknown"
        actual = Decimal(self.value.value)
        matches = {
            "gt": actual > self.target,
            "ge": actual >= self.target,
            "eq": actual == self.target,
            "le": actual <= self.target,
            "lt": actual < self.target,
        }
        return "satisfied" if matches[self.comparator] else "unsatisfied"

    @property
    def baseline_change(self) -> Decimal | None:
        if self.value.kind == "unknown" or self.baseline.kind == "unknown":
            return None
        return Decimal(self.value.value) - self.baseline.value


class MetricSourceFact(ManagementContract):
    source: SourceRevisionRef
    head: SourceHead
    source_event: SourceTime
    ingested_at: AwareDatetime

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        require_company(self.company_id, self.source, self.head)
        if self.head.current != self.source:
            raise ValueError("Measurement source must match its qualified current head")
        return self


class MetricWorkFact(ManagementContract):
    work: RunBinding
    registration_sha256: SHA256
    acceptance_id: UUID | None
    acceptance_sha256: SHA256 | None
    receipt_id: UUID | None
    accepted_at: AwareDatetime | None = None
    receipt_recorded_at: AwareDatetime | None = None
    proof_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    artifacts: tuple[ArtifactRevisionRef, ...] = Field(default=(), max_length=33)
    status: Literal["accepted_report", "not_accepted", "unknown"]

    @model_validator(mode="after")
    def qualified_shape(self) -> Self:
        require_company(self.company_id, self.work, *self.artifacts)
        if self.status == "accepted_report" and (
            self.acceptance_id is None
            or self.acceptance_sha256 is None
            or self.receipt_id is None
            or self.accepted_at is None
            or self.receipt_recorded_at is None
            or not self.proof_ids
            or not self.artifacts
        ):
            raise ValueError("Counted report needs exact native receipt/acceptance/proof facts")
        return self


class MetricSnapshot(ManagementContract):
    request: MetricObservationRequest
    recipe: Symbol | None
    comparison: MetricComparison
    work: tuple[MetricWorkFact, ...] = Field(min_length=1, max_length=100)
    resources: tuple[UUID, ...] = Field(default=(), max_length=6400)
    sources: tuple[MetricSourceFact, ...] = Field(default=(), max_length=6400)

    @model_validator(mode="after")
    def exact_facts(self) -> Self:
        require_company(self.company_id, self.request, *self.work, *self.sources)
        ids = tuple(row.work.task_id for row in self.work)
        if ids != self.request.task_ids:
            raise ValueError("Metric facts differ from the exact requested native selection")
        if self.comparison.value.kind == "known" and (
            any(row.status == "unknown" for row in self.work)
            or self.comparison.value.value
            != sum(row.status == "accepted_report" for row in self.work)
        ):
            raise ValueError("Known metric differs from its selected qualified native facts")
        if len(set(self.resources)) != len(self.resources):
            raise ValueError("Metric resource facts must be unique")
        return self


class MetricObservationRecord(ManagementContract):
    observation_id: UUID
    snapshot: MetricSnapshot
    snapshot_sha256: SHA256
    recorded_by: UUID
    operation_id: UUID
    audit_trace_id: UUID
    observed_at: AwareDatetime
    observation_basis: Literal["current native independent acceptance under company mutex"] = (
        "current native independent acceptance under company mutex"
    )

    @model_validator(mode="after")
    def exact_record(self) -> Self:
        require_company(self.company_id, self.snapshot)
        if self.observation_id != self.snapshot.request.observation_id or (
            self.snapshot_sha256 != canonical_sha256(self.snapshot)
        ):
            raise ValueError("Measurement record differs from its exact native snapshot")
        return self


class MetricCurrentObservation(ManagementContract):
    observation_id: UUID
    snapshot: MetricSnapshot
    recorded_at: AwareDatetime
    checked_at: AwareDatetime
    snapshot_sha256: SHA256
    comparison_result: Literal["satisfied", "unsatisfied", "unknown"]
    baseline_change: MetricDecimal | None

    @model_validator(mode="after")
    def exact_projection(self) -> Self:
        require_company(self.company_id, self.snapshot)
        if self.observation_id != self.snapshot.request.observation_id:
            raise ValueError("Current metric identifies another recorded observation")
        if (
            self.snapshot_sha256 != canonical_sha256(self.snapshot)
            or self.comparison_result != self.snapshot.comparison.result
            or self.baseline_change != self.snapshot.comparison.baseline_change
        ):
            raise ValueError("Current metric comparison differs from actual selected facts")
        return self
