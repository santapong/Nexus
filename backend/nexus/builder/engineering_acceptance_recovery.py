"""Finish protected engineering proof after known issuance without any new effect or budget."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.engineering_checker import check_engineering_change
from nexus.builder.engineering_inputs import PreparedEngineeringInput, RegisteredEngineeringInputs
from nexus.builder.engineering_pair_selection import EngineeringPairSelection
from nexus.builder.engineering_proof import EngineeringProofStorage
from nexus.builder.engineering_recovery_target import resolve_recovery_target
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import ProtectedCheckProof, WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import require_qualified_time
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.company.management.acceptance_persistence import acceptance_record, write_acceptance
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.acceptance_support import acceptance_scope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)
from nexus.harness.journal_models import CompanyControl


class EngineeringAcceptanceRecovery:
    """Trusted services reconstruct current checks; serialized pass never records acceptance."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        inputs: RegisteredEngineeringInputs,
        proof: EngineeringProofStorage,
    ) -> None:
        self.factory, self.catalog, self.inputs, self.proof = factory, catalog, inputs, proof

    async def reconcile_verified_result(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        verifier_action_id: UUID,
    ) -> WorkAcceptance:
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            pair = await self._target(session, control, lease, identity, verifier_action_id)
        scope = acceptance_scope(lease, pair.author_action_id)
        prepared = await self.inputs.load(scope, identity, pair.target, pair.verifier_action_id)
        result = check_engineering_change(prepared.command)
        reference = await self.proof.save(result)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            await self._recheck(
                session, control, lease, identity, scope, prepared, verifier_action_id
            )
            await self.proof.append_locked(session, scope, prepared, result, reference)
            await self._recheck(
                session, control, lease, identity, scope, prepared, verifier_action_id
            )
            await self.inputs.reader.revalidate_artifact_reference(
                session, control, scope, identity, reference, await db_now(session)
            )
            await self.inputs.freshness.revalidate_references(
                session, scope, (reference,), await db_now(session)
            )
            record = await self._record(session, scope, prepared, reference)
            await self._recheck(
                session, control, lease, identity, scope, prepared, verifier_action_id
            )
            await self._final_time(session, lease, scope, prepared, reference)
            return record

    async def _target(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        verifier_action_id: UUID,
    ) -> EngineeringPairSelection:
        return await resolve_recovery_target(
            session,
            control,
            lease,
            identity,
            verifier_action_id=verifier_action_id,
            catalog=self.catalog,
            inputs=self.inputs,
        )

    async def _recheck(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        scope: BrainReadScope,
        prepared: PreparedEngineeringInput,
        verifier_action_id: UUID,
    ) -> None:
        pair = await self._target(session, control, lease, identity, verifier_action_id)
        require_acceptance(
            pair.target == prepared.command.target and pair.metadata == prepared.metadata
        )
        await self.inputs.revalidate(
            session, control, scope, identity, prepared, await db_now(session)
        )

    async def _final_time(
        self,
        session: AsyncSession,
        lease: ExecutionLease,
        scope: BrainReadScope,
        prepared: PreparedEngineeringInput,
        reference: ArtifactRevisionRef,
    ) -> None:
        _, resources = await reference_sources(session, scope, (reference,))
        grants = await require_resources(session, scope, resources, await db_now(session))
        work = await execution_row(session, lease_scope(lease))
        final = await db_now(session)
        require_lease(work, lease, final)
        require_acceptance(lease.mode == "reconcile")
        require_acceptance(all(row.expires_at is None or row.expires_at > final for row in grants))
        require_qualified_time(prepared.freshness, final)
        require_acceptance(
            all(
                row.expires_at is None or row.expires_at > final
                for artifact in prepared.artifacts
                for row in artifact.contributors
            )
        )

    async def _record(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        prepared: PreparedEngineeringInput,
        reference: ArtifactRevisionRef,
    ) -> WorkAcceptance:
        from uuid import uuid5

        target = prepared.command.target
        result = check_engineering_change(prepared.command)
        key = uuid5(target.company_id, f"management.acceptance:{canonical_sha256(target)}")
        record = WorkAcceptance(
            company_id=target.company_id,
            acceptance_id=key,
            target=target,
            verdict=result.verdict,
            limitations=result.limitations,
            recorded_at=await db_now(session),
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
        previous = await session.get(ManagementWorkAcceptance, (scope.company_id, key))
        if previous is not None:
            old = acceptance_record(previous)
            require_acceptance(
                (old.target, old.proofs, old.verdict, old.limitations)
                == (record.target, record.proofs, record.verdict, record.limitations)
            )
            return old
        await write_acceptance(session, record)
        await append_event(
            session,
            scope,
            kind="verification_recorded",
            resource_id=self.proof.target.resource_id,
            action_id=target.action_id,
            deduplication_key=f"engineering.acceptance:{key}",
            now=await db_now(session),
        )
        return record
