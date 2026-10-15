"""Local temporal observations; no request DTO, permit or dated price authority."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from nexus.company.management.acceptance_freshness import QualifiedFreshness, require_qualified_time
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.core.llm.company_registry import EvaluationEvidence, ModelHealth
from nexus.execution.runtime_contracts import AttemptQuota


def require_window(value: bool) -> None:
    if not value:
        raise ManagementDeniedError("Current full-plan admission window is unavailable")


@dataclass(frozen=True)
class PlanGrantWindow:
    resource_id: UUID
    principal_id: UUID
    resource_generation: int
    grant_generation: int
    expires_at: datetime | None


@dataclass(frozen=True)
class PlanSourceWindow:
    source_id: UUID
    revision_id: UUID
    generation: int
    observed_at: datetime
    qualified: QualifiedFreshness


@dataclass(frozen=True)
class PlanModelCandidateWindow:
    registry_id: str
    registration_sha256: str
    effective_sha256: str
    health: ModelHealth
    evaluation: EvaluationEvidence

    def eligible_at(self, now: datetime) -> bool:
        return (
            now.utcoffset() is not None
            and self.health.status == "healthy"
            and self.health.checked_at <= now < self.health.expires_at
            and self.evaluation.conformance_passed
            and self.evaluation.evaluated_at <= now < self.evaluation.expires_at
        )


@dataclass(frozen=True)
class PlanChildWindow:
    binding: RunBinding
    quota: AttemptQuota
    kind: Literal["ordinary", "native", "sender"]
    profile_sha256: str | None
    candidates: tuple[PlanModelCandidateWindow, ...]

    def require_time(self, now: datetime) -> None:
        require_window(now.utcoffset() is not None)
        if self.kind == "ordinary":
            require_window(
                bool(self.candidates) and any(row.eligible_at(now) for row in self.candidates)
            )
        else:
            require_window(self.profile_sha256 is not None and not self.candidates)


@dataclass(frozen=True)
class PlanAdmissionWindow:
    """Concrete observations only; callers still need actual admission and protected proof."""

    company_id: UUID
    owner_id: UUID
    workspace_id: UUID
    payload_sha256: str
    catalog_sha256: str
    policy_version: str
    pricebook_version: str
    observed_at: datetime
    children: tuple[PlanChildWindow, ...]
    grants: tuple[PlanGrantWindow, ...]
    sources: tuple[PlanSourceWindow, ...]
    aggregate_grant_expiry: datetime | None
    aggregate_source_expiry: datetime | None
    credential: AuthenticatedWorkerIdentity

    @property
    def execution_pricing_authority(self) -> Literal["unqualified"]:
        return "unqualified"

    def require_time(self, now: datetime) -> None:
        require_window(now.utcoffset() is not None and self.observed_at <= now)
        require_window(
            isinstance(self.credential, AuthenticatedWorkerIdentity)
            and self.credential.identity.principal_id == self.owner_id
            and self.credential.identity.workspace_id == self.workspace_id
        )
        self.credential.require_time(now)
        deadlines = (
            *[row.expires_at for row in self.grants],
            self.aggregate_grant_expiry,
            self.aggregate_source_expiry,
        )
        require_window(all(value is None or now < value for value in deadlines))
        require_qualified_time(tuple(row.qualified for row in self.sources), now)
        for child in self.children:
            child.require_time(now)

    def require_same_scope(self, current: "PlanAdmissionWindow") -> None:
        """Compare immutable scope; every first/current expiry still needs its own final check."""
        require_window(
            (
                self.company_id,
                self.owner_id,
                self.workspace_id,
                self.payload_sha256,
                self.catalog_sha256,
                self.policy_version,
                self.pricebook_version,
                self.credential,
            )
            == (
                current.company_id,
                current.owner_id,
                current.workspace_id,
                current.payload_sha256,
                current.catalog_sha256,
                current.policy_version,
                current.pricebook_version,
                current.credential,
            )
        )
        require_window(
            tuple((r.binding, r.quota) for r in self.children)
            == tuple((r.binding, r.quota) for r in current.children)
            and tuple(
                (r.resource_id, r.principal_id, r.resource_generation, r.grant_generation)
                for r in self.grants
            )
            == tuple(
                (r.resource_id, r.principal_id, r.resource_generation, r.grant_generation)
                for r in current.grants
            )
            and tuple(
                (r.source_id, r.revision_id, r.generation, canonical_sha256(r.qualified.policy))
                for r in self.sources
            )
            == tuple(
                (r.source_id, r.revision_id, r.generation, canonical_sha256(r.qualified.policy))
                for r in current.sources
            )
        )
