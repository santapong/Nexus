"""Process-local material retains observations; descriptions confer no native authority."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid5

from nexus.builder.engineering_bodies import CompleteEngineeringBody
from nexus.builder.engineering_contracts import EngineeringCheckInput
from nexus.builder.engineering_metadata import EngineeringMetadata
from nexus.builder.verification_support import require_containment_configuration
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.engineering import EngineeringBasis
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import QualifiedFreshness, require_qualified_time
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_admission_window import (
    PlanChildWindow,
    PlanGrantWindow,
    PlanSourceWindow,
)
from nexus.company.management.plan_support import PlanAdmissionCatalog, validate_plan_profile
from nexus.company.management.plans import ChildAllocation
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof
from nexus.execution.runtime_contracts import ExecutionLease


@dataclass(frozen=True, slots=True)
class EngineeringIssuance:
    action: ActionProposal
    original_fence: int
    consumed_at: datetime
    reserved_at: datetime
    created_at: datetime
    receipt: ActionReceipt


@dataclass(frozen=True, slots=True)
class EngineeringPrerequisiteFacts:
    plan: PlanRevision
    acceptance: WorkAcceptance
    metadata: EngineeringMetadata
    check: ArtifactRevisionRef
    issuance: tuple[EngineeringIssuance, ...]
    current_fences: tuple[int, int]


@dataclass(frozen=True, slots=True)
class CycleEngineeringMaterial:
    facts: EngineeringPrerequisiteFacts
    command: EngineeringCheckInput
    basis: EngineeringBasis
    bodies: tuple[CompleteEngineeringBody, ...]


@dataclass(frozen=True, slots=True)
class CycleEngineeringReadProtection:
    observed_at: datetime
    freshness: tuple[QualifiedFreshness, ...]
    grants: tuple[ResourceGeneration, ...]
    credential: AuthenticatedWorkerIdentity
    lease: ExecutionLease
    catalog: PlanAdmissionCatalog
    children: tuple[ChildAllocation, ...]
    profiles: tuple[PlanChildWindow, ...]
    versions: tuple[str, str]
    grant_rows: tuple[PlanGrantWindow, ...]
    source_rows: tuple[PlanSourceWindow, ...]

    def require_time(self, now: datetime) -> None:
        require_acceptance(
            isinstance(self.credential, AuthenticatedWorkerIdentity)
            and (self.credential.identity.principal_id, self.credential.identity.workspace_id)
            == (self.lease.actor_id, self.lease.workspace_id)
        )
        require_acceptance(self.observed_at <= now < self.lease.expires_at)
        self.credential.require_time(now)
        require_qualified_time(self.freshness, now)
        require_acceptance(
            all(row.expires_at is None or row.expires_at > now for row in self.grants)
        )
        for child in self.children:
            validate_plan_profile(self.catalog, child, now)
        for profile in self.profiles:
            profile.require_time(now)


@dataclass(frozen=True, slots=True)
class CurrentEngineeringProof:
    material: CycleEngineeringMaterial
    strategy: StrategyCurrentProof
    initial: CycleEngineeringReadProtection
    current: CycleEngineeringReadProtection
    composition: tuple[object, ...]
    catalog_sha256: str

    def require_time(self, now: datetime) -> None:
        require_acceptance(self.initial.observed_at <= self.current.observed_at <= now)
        self.initial.require_time(now)
        self.current.require_time(now)
        self.strategy.require_time(now)
        for body in self.material.bodies:
            require_qualified_time(body.freshness, now)
            require_acceptance(
                all(
                    row.expires_at is None or row.expires_at > now
                    for row in body.first.contributors
                )
            )
            require_acceptance(
                all(
                    row.availability == "available"
                    and (row.fresh_until is None or row.fresh_until > now)
                    for row in body.first.source_heads
                )
            )


def cycle_engineering_scope(lease: ExecutionLease, identity: VerifiedIdentity) -> BrainReadScope:
    require_acceptance(
        (lease.actor_id, lease.workspace_id) == (identity.principal_id, identity.workspace_id)
    )
    return BrainReadScope(
        company_id=lease.company_id,
        workspace_id=lease.workspace_id,
        principal_id=identity.principal_id,
        operation_id=uuid5(lease.segment_id, "cycle-engineering-prerequisite:v1"),
        trace_id=lease.trace_id,
        task_id=lease.task_id,
        task_trace_id=lease.trace_id,
        actor_id=lease.actor_id,
    )


def require_matching_composition(current: tuple[object, ...], original: tuple[object, ...]) -> None:
    require_acceptance(
        bool(current)
        and len(current) == len(original)
        and all(a is b for a, b in zip(current[:-1], original[:-1], strict=True))
        and current[-1] == original[-1]
    )


if TYPE_CHECKING:
    from nexus.company.cycle_artifacts.engineering_prerequisite_reader import CycleEngineeringReader


def cycle_engineering_composition(reader: "CycleEngineeringReader") -> tuple[object, ...]:
    require_acceptance(
        reader.artifacts.factory is reader.factory is reader.freshness._factory
        and reader.strategy.artifacts is reader.artifacts
        and reader.strategy.blobs is reader.artifacts.blobs
        and reader.proof.blobs is reader.artifacts.blobs
        and reader.strategy.policies is reader.freshness._policies
        and reader.freshness._policies.policy(reader.summary_policy.source_symbol)
        == reader.summary_policy
        and reader.freshness._policies.policy(reader.proof.policy.source_symbol)
        == reader.proof.policy
    )
    require_containment_configuration(reader.containment_store, reader.execution_method_sha256)
    fingerprints = (
        canonical_sha256(reader.catalog),
        canonical_sha256(reader.strategy.catalog),
        canonical_sha256(reader.strategy.production_policy),
        canonical_sha256(reader.strategy.rules),
        canonical_sha256(reader.proof.policy),
        canonical_sha256(reader.summary_policy),
        canonical_sha256(reader.proof.target),
        canonical_sha256(reader.source.metadata),
        tuple((key, canonical_sha256(row)) for key, row in sorted(reader.declarations.items())),
        reader.results.root,
        reader.source.repository,
        reader.read_resources,
        reader.execution_method_sha256,
        reader.containment_store.root if reader.containment_store else None,
    )
    return (
        reader.factory,
        reader.catalog,
        reader.artifacts,
        reader.artifacts.blobs,
        reader.freshness,
        reader.freshness._policies,
        reader.results,
        reader.containment_store,
        reader.source,
        reader.proof,
        reader.proof.blobs,
        reader.strategy,
        reader.strategy.sources,
        fingerprints,
    )
