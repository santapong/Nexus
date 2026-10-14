"""Existing owner report/commitment references describe one bounded native occurrence."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.management.base import (
    SHA256,
    ExactUSD,
    ManagementContract,
    ValueContract,
    require_company,
)
from nexus.company.management.commitment_contracts import CommitmentRevisionRef
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactRule
from nexus.company.management.goals import DueIntent
from nexus.company.management.operating_report_contracts import ReportSelection
from nexus.harness.journal_contracts import ActionRecord


class NativeReportProfileRef(ManagementContract):
    """Selectors/checksums never supply owner, schedule, actor or approval authority."""

    report_id: UUID
    report_sha256: SHA256
    selection_sha256: SHA256
    commitment: CommitmentRevisionRef
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_native_refs(self) -> Self:
        require_company(self.company_id, self.commitment)
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Native profile evidence identities must be exact and unique")
        return self


class NativeReportOperatingProfile(ManagementContract):
    reference: NativeReportProfileRef
    selection: ReportSelection
    due: DueIntent

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(self.company_id, self.reference, self.selection)
        return self


class NativeReportPreparationPolicy(ValueContract):
    """Server configuration fixes tool/targets/cost; no standing permission is added."""

    recipe_version: Literal["native-report-profile-v1"] = "native-report-profile-v1"
    rules: tuple[GeneratedArtifactRule, ...] = Field(min_length=2, max_length=2)
    estimated_cost_usd: ExactUSD = Decimal("0.03")

    @model_validator(mode="after")
    def exact_tools(self) -> Self:
        if {row.tool for row in self.rules} != {
            "company.report.write.v1",
            "company.report.check.v1",
        }:
            raise ValueError("Native preparation requires both exact write/check rules")
        return self


class NativeReportPreparedAction(ManagementContract):
    """A pending/replayed native journal fact supplies no new execution permit."""

    profile: NativeReportProfileRef
    phase: Literal["author", "verifier"]
    action: ActionRecord
    exact_approval_required: Literal[True] = True
    scheduled: Literal[False] = False
    executed: Literal[False] = False
    model_requests: Literal[0] = 0

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(self.company_id, self.profile, self.action)
        return self
