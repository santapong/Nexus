"""Two-phase protected P/C publication; actual issuance remains in EffectStore."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_input_support import CLASSIFICATIONS, artifact_input_closure
from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.input_reader import CycleInputReader
from nexus.company.cycle_artifacts.intent_check import require_material_pins
from nexus.company.cycle_artifacts.issued_facts import require_cycle_publication_intent_locked
from nexus.company.cycle_artifacts.original_reader import CycleOriginalReader
from nexus.company.cycle_artifacts.production import CycleOutputManifest
from nexus.company.cycle_artifacts.publication_contracts import (
    CycleAuthorMaterial,
    CycleCheckMaterial,
    CyclePublicationProtection,
)
from nexus.company.cycle_artifacts.publication_rows import (
    append_author_locked,
    append_check_locked,
    require_author_replay_locked,
    require_check_replay_locked,
)
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.publication_protection import require_credential
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)
from nexus.harness.authorization_source import require_action_authority
from nexus.harness.journal_models import CompanyControl, JournalAction


def require_publication_state(
    effect: EffectIntent,
    outputs: tuple[ArtifactRevisionRef, ...],
    *,
    exists: bool,
    current_fence: int,
) -> None:
    """Compare every ordered output; unknown/failed history cannot be repaired into success."""
    require_acceptance(bool(outputs) and all(r.company_id == effect.company_id for r in outputs))
    if effect.state == "intent":
        require_acceptance(effect.receipt_json is None and effect.intent_fence == current_fence)
        return
    require_acceptance(exists and effect.state == "succeeded" and effect.receipt_json is not None)
    assert effect.receipt_json is not None
    receipt = ActionReceipt.model_validate_json(effect.receipt_json)
    require_acceptance(
        (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
            receipt.outcome,
        )
        == (
            effect.company_id,
            effect.action_id,
            effect.task_id,
            effect.trace_id,
            effect.proposal_hash,
            "succeeded",
        )
        and tuple((r.company_id, r.artifact_id, r.revision, r.sha256) for r in receipt.artifacts)
        == tuple((r.company_id, r.artifact_id, r.revision, r.sha256) for r in outputs)
    )


class CycleDeliverableStore:
    """Concrete actual reader/blob composition; constructors grant no permission or effect."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        blobs: BrainBlobStore,
        inputs: CycleInputReader,
        originals: CycleOriginalReader,
    ) -> None:
        require_acceptance(
            type(inputs) is CycleInputReader
            and type(originals) is CycleOriginalReader
            and inputs.factory is originals.factory is factory
            and inputs.blobs is originals.blobs is blobs
            and originals.inputs is inputs
        )
        self.factory, self.blobs, self.inputs, self.originals = factory, blobs, inputs, originals
        self._bound = (factory, blobs, inputs, originals)

    def composition(self) -> tuple[object, ...]:
        require_acceptance(
            all(
                a is b
                for a, b in zip(
                    (self.factory, self.blobs, self.inputs, self.originals),
                    self._bound,
                    strict=True,
                )
            )
        )
        return (*self._bound, self.inputs.composition(), self.originals.composition())

    def require_composition(self, original: tuple[object, ...]) -> None:
        current = self.composition()
        require_acceptance(current == original)
        self.inputs.require_composition(original[-2])  # type: ignore[arg-type]
        self.originals.require_composition(original[-1])  # type: ignore[arg-type]

    @staticmethod
    def references(
        material: CycleAuthorMaterial | CycleCheckMaterial,
    ) -> tuple[ArtifactRevisionRef, ...]:
        if type(material) is CycleAuthorMaterial:
            return tuple(row.artifact for row in material.prepared.manifest.parts)
        require_acceptance(type(material) is CycleCheckMaterial)
        assert isinstance(material, CycleCheckMaterial)
        return (material.prepared.artifact,)

    async def _exists(
        self, session: AsyncSession, outputs: tuple[ArtifactRevisionRef, ...]
    ) -> bool:
        found = []
        for ref in outputs:
            found.append(
                await session.scalar(
                    select(BrainArtifactRevision.artifact_revision_id).where(
                        BrainArtifactRevision.company_id == ref.company_id,
                        BrainArtifactRevision.artifact_revision_id == ref.artifact_revision_id,
                    )
                )
            )
        require_acceptance(
            all(row is None for row in found) or all(row is not None for row in found)
        )
        return all(row is not None for row in found)

    async def _gate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        material: CycleAuthorMaterial | CycleCheckMaterial,
        exists: bool,
        credential: AuthenticatedWorkerIdentity,
    ) -> CyclePublicationProtection:
        """Read actual own issuance and exact owner approval without issuing another permit."""
        await require_strategy_application_role(session)
        require_lease(work, lease, await db_now(session), execute=True)
        action_id = material.prepared.action_id
        scope = self.inputs.scope(lease, identity, action_id)
        require_credential(credential, identity, scope, await db_now(session))
        if type(material) is CycleAuthorMaterial:
            read = await self.inputs.revalidate_author_locked(
                session, control, work, lease, identity, material, credential=credential
            )
        else:
            assert isinstance(material, CycleCheckMaterial)
            read = await self.originals.revalidate_check_locked(
                session, control, work, lease, identity, material, credential=credential
            )
        record = await session.get(JournalAction, action_id)
        require_acceptance(record is not None and record.approval_json is not None)
        assert record is not None and record.approval_json is not None
        action = ActionProposal.model_validate_json(record.proposal_json)
        require_material_pins(self.inputs, work, action, material)
        issued = await require_cycle_publication_intent_locked(session, work, action, record)
        require_publication_state(
            issued.effect, self.references(material), exists=exists, current_fence=lease.fence
        )
        await require_action_authority(
            session,
            control,
            record,
            lease_scope(lease),
            identity,
            await db_now(session),
            action.preconditions,
        )
        approval = ApprovalDecision.model_validate_json(record.approval_json)
        require_acceptance(
            approval.approver_id == control.owner_id and approval.decision == "approved"
        )
        material.protection.require_same_scope(read)
        return CyclePublicationProtection(read, approval, lease)

    async def _replay(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        material: CycleAuthorMaterial | CycleCheckMaterial,
    ) -> None:
        scope = self.inputs.scope(lease, identity, material.prepared.action_id)
        rule = (
            self.inputs.rules.rule(material.prepared.basis.artifact_kind, "write")
            if isinstance(material, CycleAuthorMaterial)
            else self.inputs.rules.rule(material.command.artifact_kind, "check")
        )
        if isinstance(material, CycleAuthorMaterial):
            await require_author_replay_locked(
                session, scope, material.prepared, rule, self.blobs.storage_symbol
            )
            inputs = material.prepared.basis.inputs
        else:
            await require_check_replay_locked(
                session, scope, material.prepared, rule, self.blobs.storage_symbol
            )
            inputs = material.prepared.inputs
        refs = self.references(material)
        for reference in refs:
            await self.inputs.artifacts.revalidate_artifact_reference(
                session, control, scope, identity, reference, await db_now(session)
            )
        expected = {r.artifact_revision_id: r for r in (*inputs.artifacts, *refs)}
        require_acceptance(
            len(expected) <= 33 and sum(r.byte_length for r in expected.values()) <= 8650752
        )
        closure = await artifact_input_closure(
            session, scope, tuple(r.artifact_revision_id for r in refs)
        )
        require_acceptance(
            set(closure.artifact_revision_ids) == set(expected)
            and set(closure.resource_ids)
            == set(inputs.required_resource_ids) | {rule.target.resource_id}
            and all(
                CLASSIFICATIONS.index(c)
                <= CLASSIFICATIONS.index(rule.policies[0].data_classification)
                for c in closure.classifications
            )
        )

    async def _publish(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        material: CycleAuthorMaterial | CycleCheckMaterial,
        credential: AuthenticatedWorkerIdentity,
    ) -> None:
        # Keep one >50-line two-phase publication/replay and final-window rollback boundary.
        original = self.composition()
        refs = self.references(material)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work = await execution_row(session, lease_scope(lease))
            exists = await self._exists(session, refs)
            initial = await self._gate(
                session, control, work, lease, identity, material, exists, credential
            )
            self.require_composition(original)
            if exists:
                await self._replay(session, control, lease, identity, material)
                final = await db_now(session)
                self.require_composition(original)
                require_lease(work, lease, final, execute=True)
                credential.require_time(final)
                material.protection.require_time(final)
                initial.require_time(final)
                return
        bodies = (
            (material.prepared.typed_json, material.prepared.human_export)
            if isinstance(material, CycleAuthorMaterial)
            else (material.prepared.raw_bytes,)
        )
        for ref, raw in zip(refs, bodies, strict=True):
            await self.blobs.save(ref, raw)
            self.require_composition(original)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work = await execution_row(session, lease_scope(lease))
            exists = await self._exists(session, refs)
            current = await self._gate(
                session, control, work, lease, identity, material, exists, credential
            )
            self.require_composition(original)
            scope = self.inputs.scope(lease, identity, material.prepared.action_id)
            if not exists:
                if isinstance(material, CycleAuthorMaterial):
                    rule = self.inputs.rules.rule(material.prepared.basis.artifact_kind, "write")
                    await append_author_locked(
                        session,
                        scope,
                        material.prepared,
                        rule,
                        self.blobs.storage_symbol,
                        await db_now(session),
                    )
                else:
                    rule = self.inputs.rules.rule(material.command.artifact_kind, "check")
                    await append_check_locked(
                        session,
                        scope,
                        material.prepared,
                        rule,
                        self.blobs.storage_symbol,
                        await db_now(session),
                    )
            await self._replay(session, control, lease, identity, material)
            await session.flush()
            final = await db_now(session)
            self.require_composition(original)
            require_lease(work, lease, final, execute=True)
            credential.require_time(final)
            material.protection.require_time(final)
            initial.require_time(final)
            current.require_time(final)

    async def publish_author(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        material: CycleAuthorMaterial,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> CycleOutputManifest:
        """Publish/replay one already-issued ordered pair; create no receipt or acceptance."""
        require_acceptance(type(material) is CycleAuthorMaterial)
        await self._publish(lease, identity, material, credential)
        return material.prepared.manifest

    async def publish_check(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        material: CycleCheckMaterial,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> ArtifactRevisionRef:
        """Publish/replay an already-issued independent mechanical check."""
        require_acceptance(type(material) is CycleCheckMaterial)
        await self._publish(lease, identity, material, credential)
        return material.prepared.artifact
