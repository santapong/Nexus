"""Trusted engineering proof/publication flow, separate from M1 completion and reports."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.engineering_checker import check_engineering_change
from nexus.builder.engineering_contracts import EngineeringCheckResult
from nexus.builder.engineering_inputs import PreparedEngineeringInput, RegisteredEngineeringInputs
from nexus.builder.engineering_proof import EngineeringProofStorage
from nexus.builder.engineering_targets import resolve_engineering_target
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import (
    ProtectedCheckProof,
    VerificationSpec,
    WorkAcceptance,
)
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import QualifiedFreshness, require_qualified_time
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.company.management.acceptance_persistence import acceptance_record, write_acceptance
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.acceptance_support import acceptance_scope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)
from nexus.harness.journal_models import CompanyControl


class EngineeringWorkAcceptanceStore:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        inputs: RegisteredEngineeringInputs,
        proof: EngineeringProofStorage,
        *,
        credential: AuthenticatedWorkerIdentity | None = None,
    ) -> None:
        if credential is not None and not isinstance(credential, AuthenticatedWorkerIdentity):
            raise ValueError("Engineering authenticated credential witness unavailable")
        self.factory, self.catalog, self.inputs, self.proof = factory, catalog, inputs, proof
        self.credential = credential

    async def _target(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
    ) -> VerificationSpec:
        work = await execution_row(session, lease_scope(lease))
        require_lease(work, lease, await db_now(session), execute=True)
        await require_management_execution(
            session,
            control,
            work,
            identity,
            self.catalog,
            self.inputs.reader,
            self.inputs.freshness,
        )
        return await resolve_engineering_target(session, control, lease, action_id)

    async def _prepare(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        author_action_id: UUID,
        verifier_action_id: UUID,
    ) -> tuple[BrainReadScope, PreparedEngineeringInput]:
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            target = await self._target(session, control, lease, identity, author_action_id)
        scope = acceptance_scope(lease, author_action_id)
        prepared = await self.inputs.load(scope, identity, target, verifier_action_id)
        return scope, prepared

    async def _recheck(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        prepared: PreparedEngineeringInput,
    ) -> None:
        target = await self._target(
            session, control, lease, identity, prepared.command.target.action_id
        )
        require_acceptance(target == prepared.command.target)
        await self.inputs.revalidate(
            session, control, scope, identity, prepared, await db_now(session)
        )

    async def prepare_verified_result(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        author_action_id: UUID,
        verifier_action_id: UUID,
    ) -> ArtifactRevisionRef:
        scope, prepared = await self._prepare(lease, identity, author_action_id, verifier_action_id)
        result = check_engineering_change(prepared.command)
        reference = await self.proof.save(result)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            await self._recheck(session, control, lease, scope, identity, prepared)
            await self.proof.append_locked(session, scope, prepared, result, reference)
            await self._recheck(session, control, lease, scope, identity, prepared)
            await self.inputs.reader.revalidate_artifact_reference(
                session, control, scope, identity, reference, await db_now(session)
            )
            await self.inputs.freshness.revalidate_references(
                session, scope, (reference,), await db_now(session)
            )
            await self._final_time(session, lease, prepared)
        return reference

    async def publish_verified_result(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        author_action_id: UUID,
        verifier_action_id: UUID,
        protected_result: ArtifactRevisionRef,
    ) -> WorkAcceptance:
        scope, prepared = await self._prepare(lease, identity, author_action_id, verifier_action_id)
        expected = check_engineering_change(prepared.command)
        protected, proof_freshness = await self._checked_proof(
            scope, identity, expected, protected_result
        )
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            await self._recheck(session, control, lease, scope, identity, prepared)
            await self.proof.require_stored_locked(
                session, scope, prepared, expected, protected_result
            )
            await self.inputs.reader.revalidate_artifact(
                session, control, scope, identity, protected, await db_now(session)
            )
            await self.inputs.freshness.revalidate(
                session, scope, proof_freshness, await db_now(session)
            )
            record = await self._upsert_record(session, scope, prepared, expected, protected_result)
            await self._recheck(session, control, lease, scope, identity, prepared)
            await self.inputs.reader.revalidate_artifact(
                session, control, scope, identity, protected, await db_now(session)
            )
            await self.inputs.freshness.revalidate(
                session, scope, proof_freshness, await db_now(session)
            )
            await self._final_time(session, lease, prepared)
            return record

    async def _final_time(
        self, session: AsyncSession, lease: ExecutionLease, prepared: PreparedEngineeringInput
    ) -> None:
        scope = acceptance_scope(lease, prepared.command.target.action_id)
        reference = self.proof.reference(check_engineering_change(prepared.command))
        _, resources = await reference_sources(session, scope, (reference,))
        grants = await require_resources(session, scope, resources, await db_now(session))
        work = await execution_row(session, lease_scope(lease))
        final = await db_now(session)
        if self.credential is not None:
            require_acceptance(
                (self.credential.identity.principal_id, self.credential.identity.workspace_id)
                == (lease.actor_id, lease.workspace_id)
            )
            self.credential.require_time(final)
        require_lease(work, lease, final, execute=True)
        require_acceptance(all(row.expires_at is None or row.expires_at > final for row in grants))
        require_qualified_time(prepared.freshness, final)
        require_acceptance(
            all(
                row.expires_at is None or row.expires_at > final
                for artifact in prepared.artifacts
                for row in artifact.contributors
            )
        )

    @staticmethod
    def _record(
        prepared: PreparedEngineeringInput,
        result: EngineeringCheckResult,
        reference: ArtifactRevisionRef,
        now: datetime,
    ) -> WorkAcceptance:
        target = prepared.command.target
        key = uuid5(target.company_id, f"management.acceptance:{canonical_sha256(target)}")
        return WorkAcceptance(
            company_id=target.company_id,
            acceptance_id=key,
            target=target,
            verdict=result.verdict,
            limitations=result.limitations,
            recorded_at=now,
            proofs=(
                ProtectedCheckProof(
                    company_id=target.company_id,
                    proof_id=uuid5(key, reference.artifact_revision_id.hex),
                    recipe=target.check_recipe,
                    result_artifact=reference,
                    target_sha256=canonical_sha256(target),
                ),
            ),
        )

    async def _checked_proof(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        expected: EngineeringCheckResult,
        protected_result: ArtifactRevisionRef,
    ) -> tuple[ArtifactSlice, tuple[QualifiedFreshness, ...]]:
        require_acceptance(protected_result == self.proof.reference(expected))
        protected = await self.inputs.reader.bounded_artifact(
            scope,
            identity,
            protected_result.artifact_revision_id,
            start_byte=0,
            max_bytes=16384,
            include_history=False,
        )
        require_acceptance(
            protected.artifact == protected_result
            and not protected.has_more
            and protected.span.start_byte == 0
        )
        raw = protected.text.encode()
        require_acceptance(
            len(raw) == protected_result.byte_length
            and hashlib.sha256(raw).hexdigest() == protected_result.sha256
            and EngineeringCheckResult.model_validate_json(raw) == expected
        )
        proof_freshness = await self.inputs.freshness.prepare(scope, identity, (protected,))
        return protected, proof_freshness

    async def _upsert_record(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        prepared: PreparedEngineeringInput,
        expected: EngineeringCheckResult,
        protected_result: ArtifactRevisionRef,
    ) -> WorkAcceptance:
        record = self._record(prepared, expected, protected_result, await db_now(session))
        previous = await session.get(
            ManagementWorkAcceptance, (scope.company_id, record.acceptance_id)
        )
        if previous is not None:
            old = acceptance_record(previous)
            require_acceptance(
                (old.target, old.proofs, old.verdict, old.limitations)
                == (record.target, record.proofs, record.verdict, record.limitations)
            )
            record = old
        else:
            await write_acceptance(session, record)
            await append_event(
                session,
                scope,
                kind="verification_recorded",
                resource_id=self.proof.target.resource_id,
                action_id=prepared.command.target.action_id,
                deduplication_key=f"engineering.acceptance:{record.acceptance_id}",
                now=await db_now(session),
            )
        return record
