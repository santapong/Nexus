"""Immutable mandate/charter declaration snapshots; operative owner checks belong to stores."""

from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.company.management.base import RevisionRef, require_company
from nexus.company.management.canonical import canonical_sha256


class MandateRevision(RevisionRef):
    mandate: CompanyMandate
    recorded_by: UUID
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact_snapshot(self) -> Self:
        require_company(self.company_id, self.mandate)
        if self.version != self.mandate.version or self.sha256 != canonical_sha256(self.mandate):
            raise ValueError("Mandate revision/hash differs from its exact payload")
        if self.recorded_by != self.mandate.owner_id:
            raise ValueError("Owner mandate record must name its declared owner")
        if self.mandate.work_cap_usd > self.mandate.daily_cap_usd:
            raise ValueError("Mandate cannot declare work allowance above its daily cap")
        return self


class CharterRevisionRef(RevisionRef):
    department_id: UUID


class CharterRevision(CharterRevisionRef):
    charter: DepartmentCharter
    mandate: RevisionRef
    recorded_by: UUID
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact_snapshot(self) -> Self:
        require_company(self.company_id, self.charter, self.mandate)
        if (self.department_id, self.version) != (self.charter.department_id, self.charter.version):
            raise ValueError("Charter revision identity differs from its payload")
        if self.sha256 != canonical_sha256(self.charter):
            raise ValueError("Charter digest differs from its exact payload")
        if any(
            len(values) > 32
            for values in (
                self.charter.responsibilities,
                self.charter.allowed_tools,
                self.charter.resource_scopes,
                self.charter.deliverables,
            )
        ):
            raise ValueError("Charter declarations exceed their bounded lists")
        return self
