"""Current native strategy proof persistence; no raw verdict endpoint or M1 completion mutation."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.event_store import append_event
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.company.management.acceptance_persistence import acceptance_record, write_acceptance
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.acceptance import build_strategy_acceptance
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_protection import strategy_publication_scope
from nexus.company.strategy.verifier_receipt import require_strategy_verifier_receipt
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)


async def _persist_locked(session: AsyncSession, proposed: WorkAcceptance) -> WorkAcceptance:
    """One target acceptance is immutable, including all saved proof rows on exact replay."""
    old = await session.get(ManagementWorkAcceptance, (proposed.company_id, proposed.acceptance_id))
    if old is None:
        await write_acceptance(session, proposed)
        old = await session.get(
            ManagementWorkAcceptance, (proposed.company_id, proposed.acceptance_id)
        )
        require_acceptance(old is not None)
    assert old is not None
    record = acceptance_record(old)
    require_acceptance(
        old.recorded_at == record.recorded_at
        and record.target == proposed.target
        and record.proofs == proposed.proofs
        and record.verdict == proposed.verdict
        and record.limitations == proposed.limitations
    )
    proofs = tuple(
        (
            await session.scalars(
                select(ManagementAcceptanceProof)
                .where(
                    ManagementAcceptanceProof.company_id == record.company_id,
                    ManagementAcceptanceProof.acceptance_id == record.acceptance_id,
                )
                .limit(len(record.proofs) + 1)
            )
        ).all()
    )
    expected = {row.proof_id: row for row in record.proofs}
    require_acceptance(
        len(proofs) == len(expected) and {row.proof_id for row in proofs} == set(expected)
    )
    for row in proofs:
        wanted = expected.get(row.proof_id)
        require_acceptance(wanted is not None)
        assert wanted is not None
        require_acceptance(
            (
                row.company_id,
                row.acceptance_id,
                row.artifact_revision_id,
                row.artifact_sha256,
                row.check_recipe,
                row.target_sha256,
                row.proof_json,
            )
            == (
                record.company_id,
                record.acceptance_id,
                wanted.result_artifact.artifact_revision_id,
                wanted.result_artifact.sha256,
                wanted.recipe,
                wanted.target_sha256,
                wanted.model_dump_json(),
            )
        )
    return record


class StrategyAcceptanceStore:
    """Configured concrete reader and actual receipt gate; caller DTOs cannot authorize proof."""

    def __init__(
        self, factory: async_sessionmaker[AsyncSession], reader: StrategyInputReader
    ) -> None:
        if reader.artifacts.factory is not factory:
            raise ValueError("Strategy acceptance requires its actual reader factory")
        self.factory, self.reader = factory, reader

    async def publish_verified_result(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        author_action_id: UUID,
        verifier_action_id: UUID,
        protected_result: ArtifactRevisionRef,
        credential: AuthenticatedWorkerIdentity,
    ) -> WorkAcceptance:
        """Append from current S/SV, complete protected check and actual succeeded SV receipt."""
        # This >50-line proof transaction retains every initial/current window through final writes.
        scope = strategy_publication_scope(lease, verifier_action_id)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            await require_strategy_application_role(session)
            initial = await self.reader.load_check_locked(
                session, control, lease, identity, author_action_id, credential=credential
            )
            facts = await require_strategy_verifier_receipt(
                session,
                control,
                lease,
                identity,
                initial.command.target,
                verifier_action_id=verifier_action_id,
                protected_result=protected_result,
                rule=self.reader.rules.check,
                credential=credential,
                artifacts=self.reader.artifacts,
            )
            result_protection = await self.reader.protect_check_result_locked(
                session,
                control,
                lease,
                identity,
                initial,
                verifier_action_id,
                protected_result,
                credential=credential,
            )
            artifact = await session.get(
                BrainArtifactRevision, (lease.company_id, protected_result.artifact_revision_id)
            )
            require_acceptance(artifact is not None)
            assert artifact is not None
            raw = artifact.raw_text.encode()
            proposed = build_strategy_acceptance(
                initial.command, initial.inputs, facts, raw, await db_now(session)
            )
            result = await _persist_locked(session, proposed)
            await append_event(
                session,
                scope,
                kind="verification_recorded",
                resource_id=artifact.resource_id,
                action_id=author_action_id,
                deduplication_key=f"strategy-acceptance:{result.acceptance_id}",
                now=result.recorded_at,
            )
            await session.flush()
            current = await self.reader.load_check_locked(
                session, control, lease, identity, author_action_id, credential=credential
            )
            require_acceptance(
                current.command == initial.command
                and current.inputs == initial.inputs
                and current.classification == initial.classification
            )
            current_facts = await require_strategy_verifier_receipt(
                session,
                control,
                lease,
                identity,
                current.command.target,
                verifier_action_id=verifier_action_id,
                protected_result=protected_result,
                rule=self.reader.rules.check,
                credential=credential,
                artifacts=self.reader.artifacts,
            )
            require_acceptance(current_facts == facts)
            current_result = await self.reader.protect_check_result_locked(
                session,
                control,
                lease,
                identity,
                current,
                verifier_action_id,
                protected_result,
                credential=credential,
            )
            current_artifact = await session.get(
                BrainArtifactRevision, (lease.company_id, protected_result.artifact_revision_id)
            )
            require_acceptance(current_artifact is not None)
            assert current_artifact is not None
            require_acceptance(current_artifact.raw_text.encode() == raw)
            work = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_acceptance(result.recorded_at <= now)
            require_lease(work, lease, now, execute=True)
            for protection in (
                initial.protection,
                result_protection,
                current.protection,
                current_result,
            ):
                protection.require_time(now)
            credential.require_time(now)
            return result
