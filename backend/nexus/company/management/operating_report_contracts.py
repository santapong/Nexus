"""Immutable native report selections and captured facts, never supplied report authority."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.sources import SourceHead
from nexus.company.management.base import SHA256, ManagementContract, Name, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_rules import (
    ChargeProjection,
    OperatingProjection,
    WorkLineage,
    WorkReportFacts,
)


class ReportSelection(ManagementContract):
    """Server-resolved immutable owner selection; IDs cannot allocate or grant work."""

    plan: PlanRevisionRef
    author: RunBinding
    verifier: RunBinding
    work: tuple[RunBinding, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        require_company(self.company_id, self.plan, self.author, self.verifier, *self.work)
        ids = tuple(row.task_id for row in self.work)
        if len(set(ids)) != len(ids) or self.author.task_id in ids or self.verifier.task_id in ids:
            raise ValueError("Report selection cannot duplicate or include its output procedures")
        if self.author.actor_id == self.verifier.actor_id:
            raise ValueError("Shared report verifier must be independent")
        return self


class ReportData(ManagementContract):
    """Current native read facts without an owner identity substituted for a verifier."""

    lineage: tuple[WorkLineage, ...] = Field(min_length=1, max_length=101)
    work: tuple[WorkReportFacts, ...] = Field(default=(), max_length=100)
    charges: tuple[ChargeProjection, ...] = Field(default=(), max_length=1000)
    missing_charge_ids: tuple[UUID, ...] = Field(default=(), max_length=1000)
    owner_decision_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    required_resource_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    resource_generations: tuple[tuple[UUID, int], ...] = Field(default=(), max_length=32)
    source_heads: tuple[SourceHead, ...] = Field(default=(), max_length=64)
    blockers: tuple[Name, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(
            self.company_id, *self.lineage, *self.work, *self.charges, *self.source_heads
        )
        return self


class SavedOperatingReport(ManagementContract):
    """Stored owner-authored selection+facts+projection envelope, not model-declared input."""

    report_id: UUID
    ledger_basis: Literal["selected_work_lifetime"] = "selected_work_lifetime"
    selection: ReportSelection
    period_start: AwareDatetime
    period_end: AwareDatetime
    observed_at: AwareDatetime
    created_by: UUID
    data: ReportData
    projection: OperatingProjection
    data_sha256: SHA256

    @model_validator(mode="after")
    def exact_envelope(self) -> Self:
        require_company(self.company_id, self.selection, self.data, self.projection)
        snapshot = self.projection.snapshot
        if self.period_end <= self.period_start or self.data_sha256 != canonical_sha256(self.data):
            raise ValueError("Report envelope data hash or period is inconsistent")
        if (
            snapshot.report_id,
            snapshot.period_start,
            snapshot.period_end,
            snapshot.ledger.observed_at,
        ) != (self.report_id, self.period_start, self.period_end, self.observed_at):
            raise ValueError("Report projection differs from its immutable envelope")
        return self
