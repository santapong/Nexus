"""Bounded current measurement pages; discovery is not execution or saved-value authority."""

from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.management.base import ManagementContract, require_company
from nexus.company.management.metric_contracts import MetricCurrentObservation

MAX_METRIC_PAGE_BYTES = 2_097_152


class MetricObservationPage(ManagementContract):
    goal_id: UUID
    checked_at: AwareDatetime
    observations: tuple[MetricCurrentObservation, ...] = Field(default=(), max_length=8)
    next_after_id: UUID | None = None

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        require_company(self.company_id, *self.observations)
        if any(item.snapshot.request.goal.goal_id != self.goal_id for item in self.observations):
            raise ValueError("Metric page contains another scoped goal")
        if len({item.observation_id for item in self.observations}) != len(self.observations):
            raise ValueError("Metric page observation IDs must be unique")
        return self
