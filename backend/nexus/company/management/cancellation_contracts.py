"""Explicit permanent owner intent; activity/pause/receipt/outcome are distinct facts."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.brain.base import Flag
from nexus.company.management.base import SHA256, ManagementContract, Name, require_company
from nexus.company.management.plans import RunBinding


class CancellationCommand(ManagementContract):
    """Exact native target and reason; scope supplies actual owner/operation/audit identity."""

    target: RunBinding
    reason: Name

    @model_validator(mode="after")
    def exact_target(self) -> Self:
        """No foreign or meaningless cancellation declaration enters the store."""
        require_company(self.company_id, self.target)
        if not self.reason.strip():
            raise ValueError("Cancellation requires an explicit reason")
        return self


class OwnerCancellation(ManagementContract):
    """Immutable observed owner instruction, not a source-report/candidate completion."""

    cancellation_id: UUID
    target: RunBinding
    registration_sha256: SHA256
    reason: Name
    owner_id: UUID
    operation_id: UUID
    audit_trace_id: UUID
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def scoped(self) -> Self:
        """Structural equality never replaces signed current-owner validation."""
        require_company(self.company_id, self.target)
        return self


class InheritedCancellation(ManagementContract):
    """Closest actual stopped ancestor; a factual read cannot create authority or refunds."""

    requested_task_id: UUID
    ancestor_task_id: UUID
    inherited: Flag
    cancellation: OwnerCancellation

    @model_validator(mode="after")
    def exact_ancestry(self) -> Self:
        """Keep the described ancestor and direct/inherited label internally consistent."""
        require_company(self.company_id, self.cancellation)
        if self.ancestor_task_id != self.cancellation.target.task_id or self.inherited != (
            self.requested_task_id != self.ancestor_task_id
        ):
            raise ValueError("Cancellation inheritance metadata is inconsistent")
        return self
