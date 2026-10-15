"""Native PV/CV succeeded-proof acceptance; no raw verdict or M1 completion mutation."""

import json
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.engineering_bodies import (
    _require_windows,
    load_complete_engineering_body,
    revalidate_complete_engineering_artifact_locked,
)
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.event_store import append_event
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.cycle_artifacts.action_parameters import (
    PresentationCheckParameters,
    SupportCheckParameters,
)
from nexus.company.cycle_artifacts.check_contracts import CycleArtifactCheckInput
from nexus.company.cycle_artifacts.checker import check_cycle_artifact
from nexus.company.cycle_artifacts.issued_facts import (
    CycleVerifierFacts,
    require_cycle_verifier_facts_locked,
)
from nexus.company.cycle_artifacts.original_reader import CycleOriginalReader
from nexus.company.cycle_artifacts.publication_contracts import PreparedCycleCheck
from nexus.company.cycle_artifacts.publication_rows import require_check_replay_locked
from nexus.company.management.acceptance import ProtectedCheckProof, WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import require_qualified_time
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.company.management.acceptance_persistence import acceptance_record, write_acceptance
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)
from nexus.harness.canonical import action_hash


def build_cycle_acceptance(
    command: CycleArtifactCheckInput,
    prepared: PreparedCycleCheck,
    facts: CycleVerifierFacts,
    raw: bytes,
    recorded_at: datetime,
) -> WorkAcceptance:
    """Pure recomputation descriptions; only the native store can persist their actual proof."""
    # Keep the >50-line complete target/receipt/parameter/proof comparison in one pure boundary.
    pins, action, receipt = facts.parameters, facts.action, facts.receipt
    model = (
        PresentationCheckParameters
        if command.artifact_kind == "presentation"
        else SupportCheckParameters
    )
    checked = check_cycle_artifact(command)
    require_acceptance(
        pins == model.model_validate_json(json.dumps(action.parameters, allow_nan=False))
        and prepared.command == command
        and prepared.raw_bytes == raw == checked.model_dump_json().encode()
        and checked.verdict == "pass"
        and facts.protected_result == prepared.artifact
        and pins.author_action_id == command.target.action_id
        and pins.verification_target_sha256 == canonical_sha256(command.target)
        and pins.author_output_manifest_sha256 == canonical_sha256(command.manifest)
        and pins.output_sha256 == prepared.output_sha256
        and pins.input_snapshot_sha256 == prepared.input_snapshot_sha256
        and pins.input_manifest_sha256 == prepared.input_manifest_sha256
        and (action.company_id, action.action_id, action.task_id, action.trace_id, action.actor_id)
        == (
            command.company_id,
            prepared.action_id,
            command.target.verifier.task_id,
            command.target.verifier.trace_id,
            command.target.verifier.actor_id,
        )
        and action.tool == "company.cycle-artifact.check.v1"
        and action.tool_version == "v1"
        and (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
            receipt.outcome,
        )
        == (
            action.company_id,
            action.action_id,
            action.task_id,
            action.trace_id,
            action_hash(action),
            "succeeded",
        )
        and tuple((r.company_id, r.artifact_id, r.revision, r.sha256) for r in receipt.artifacts)
        == (
            (
                prepared.artifact.company_id,
                prepared.artifact.artifact_id,
                prepared.artifact.revision,
                prepared.artifact.sha256,
            ),
        )
        and receipt.recorded_at <= recorded_at
    )
    target_sha = canonical_sha256(command.target)
    key = uuid5(
        command.company_id, f"management.cycle-acceptance:{command.artifact_kind}:{target_sha}"
    )
    return WorkAcceptance(
        company_id=command.company_id,
        acceptance_id=key,
        target=command.target,
        verdict="pass",
        limitations=checked.limitations,
        recorded_at=recorded_at,
        proofs=(
            ProtectedCheckProof(
                company_id=command.company_id,
                proof_id=uuid5(key, prepared.artifact.artifact_revision_id.hex),
                recipe=command.target.check_recipe,
                result_artifact=prepared.artifact,
                target_sha256=target_sha,
            ),
        ),
    )


async def persist_cycle_acceptance_locked(
    session: AsyncSession, proposed: WorkAcceptance
) -> WorkAcceptance:
    """Retain original acceptance time and compare every actual proof row on exact replay."""
    # Keep original SQL+embedded time and every proof row in one cohesive >50-line replay.
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
        and (record.target, record.proofs, record.verdict, record.limitations)
        == (proposed.target, proposed.proofs, proposed.verdict, proposed.limitations)
    )
    rows = tuple(
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
    expected = {p.proof_id: p for p in record.proofs}
    require_acceptance(len(rows) == len(expected) and {p.proof_id for p in rows} == set(expected))
    for row in rows:
        wanted = expected[row.proof_id]
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


class CycleAcceptanceStore:
    """Concrete current reader plus actual succeeded check facts; no caller verdict endpoint."""

    def __init__(
        self, factory: async_sessionmaker[AsyncSession], reader: CycleOriginalReader
    ) -> None:
        require_acceptance(type(reader) is CycleOriginalReader and reader.factory is factory)
        self.factory, self.reader = factory, reader
        self._factory, self._reader = factory, reader

    def _composition(self, original: tuple[object, ...]) -> None:
        require_acceptance(self.factory is self._factory and self.reader is self._reader)
        self.reader.require_composition(original)

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
        """Reread succeeded PV/CV/check/original windows before immutable proof persistence."""
        # Keep this >50-line prepare/read/write/final-clock proof boundary in one operation.
        original = self.reader.composition()
        material = await self.reader.prepare_check(
            lease, identity, author_action_id, verifier_action_id, credential=credential
        )
        self._composition(original)
        scope = self.reader.scope(lease, identity, verifier_action_id)
        require_acceptance(material.prepared.artifact == protected_result)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work = await execution_row(session, lease_scope(lease))
            initial = await self.reader.revalidate_check_locked(
                session, control, work, lease, identity, material, credential=credential
            )
            first_facts = await require_cycle_verifier_facts_locked(
                self.reader,
                session,
                control,
                work,
                lease,
                identity,
                material.command.target,
                verifier_action_id,
                protected_result,
                credential=credential,
            )
            self._composition(original)
        body = await load_complete_engineering_body(
            self.reader.artifacts, self.reader.freshness, scope, identity, protected_result
        )
        self._composition(original)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work = await execution_row(session, lease_scope(lease))
            current = await self.reader.revalidate_check_locked(
                session, control, work, lease, identity, material, credential=credential
            )
            facts = await require_cycle_verifier_facts_locked(
                self.reader,
                session,
                control,
                work,
                lease,
                identity,
                material.command.target,
                verifier_action_id,
                protected_result,
                credential=credential,
            )
            require_acceptance(facts == first_facts)
            await revalidate_complete_engineering_artifact_locked(
                self.reader.artifacts,
                session,
                control,
                scope,
                identity,
                body.first,
                await db_now(session),
            )
            rule = self.reader.rules.rule(material.command.artifact_kind, "check")
            await require_check_replay_locked(
                session, scope, material.prepared, rule, self.reader.blobs.storage_symbol
            )
            proposed = build_cycle_acceptance(
                material.command, material.prepared, facts, body.raw, await db_now(session)
            )
            record = await persist_cycle_acceptance_locked(session, proposed)
            event_key = f"cycle-acceptance:{material.command.artifact_kind}:{record.acceptance_id}"
            await append_event(
                session,
                scope,
                kind="verification_recorded",
                resource_id=rule.target.resource_id,
                action_id=author_action_id,
                deduplication_key=event_key,
                now=record.recorded_at,
            )
            await session.flush()
            require_acceptance(await persist_cycle_acceptance_locked(session, record) == record)
            event = await session.get(
                BrainEvent, (lease.company_id, uuid5(lease.company_id, event_key))
            )
            require_acceptance(event is not None)
            assert event is not None
            require_acceptance(
                (
                    event.kind,
                    event.resource_id,
                    event.action_id,
                    event.deduplication_key,
                    event.recorded_at,
                    event.trace_id,
                    event.operation_id,
                )
                == (
                    "verification_recorded",
                    rule.target.resource_id,
                    author_action_id,
                    event_key,
                    record.recorded_at,
                    scope.trace_id,
                    scope.operation_id,
                )
            )
            last = await self.reader.revalidate_check_locked(
                session, control, work, lease, identity, material, credential=credential
            )
            await revalidate_complete_engineering_artifact_locked(
                self.reader.artifacts,
                session,
                control,
                scope,
                identity,
                body.first,
                await db_now(session),
            )
            await self.reader.freshness.revalidate(
                session, scope, body.freshness, await db_now(session)
            )
            final = await db_now(session)
            self._composition(original)
            require_lease(work, lease, final, execute=True)
            credential.require_time(final)
            material.protection.require_time(final)
            initial.require_time(final)
            current.require_time(final)
            last.require_time(final)
            _require_windows(body.first, final)
            require_qualified_time(body.freshness, final)
            return record

    async def recover_verified_result(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        author_action_id: UUID,
        verifier_action_id: UUID,
        protected_result: ArtifactRevisionRef,
        credential: AuthenticatedWorkerIdentity,
    ) -> WorkAcceptance:
        """Recover from actual succeeded receipt/current own fence; create no new effect."""
        return await self.publish_verified_result(
            lease,
            identity,
            author_action_id=author_action_id,
            verifier_action_id=verifier_action_id,
            protected_result=protected_result,
            credential=credential,
        )
