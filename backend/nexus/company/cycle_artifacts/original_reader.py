"""Independent PV/CV READ of actual succeeded two-output publication and original basis."""

import asyncio
from dataclasses import replace
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.engineering_bodies import (
    BODY_READ_SECONDS,
    load_complete_engineering_body,
    revalidate_complete_engineering_artifact_locked,
)
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts import production as outputs
from nexus.company.cycle_artifacts.action_parameters import decode_cycle_action
from nexus.company.cycle_artifacts.check_contracts import CycleArtifactCheckInput
from nexus.company.cycle_artifacts.common import criteria_for
from nexus.company.cycle_artifacts.input_reader import CycleInputReader
from nexus.company.cycle_artifacts.issued_facts import require_cycle_publication_intent_locked
from nexus.company.cycle_artifacts.native_contracts import CurrentEngineeringProof
from nexus.company.cycle_artifacts.payloads import PresentationBrief, SupportDraft
from nexus.company.cycle_artifacts.publication_contracts import (
    CycleArtifactRule,
    CycleCheckMaterial,
    CycleReadProtection,
    prepare_registered_cycle_check,
    require_author_action_pins,
)
from nexus.company.cycle_artifacts.publication_rows import require_author_replay_locked
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import actual_receipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.native_report_inputs import CLASSIFICATIONS, native_manifest
from nexus.company.management.report_input_contracts import native_author
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now, lease_scope, require_lease, runtime_transaction
from nexus.harness.journal_models import CompanyControl, JournalAction


class CycleOriginalReader:
    def __init__(self, inputs: CycleInputReader) -> None:
        require_acceptance(type(inputs) is CycleInputReader)
        self.inputs = inputs
        self.factory, self.catalog = inputs.factory, inputs.catalog
        self.rules = inputs.rules
        self.artifacts, self.freshness = inputs.artifacts, inputs.freshness
        self.blobs = inputs.blobs
        self.engineering = inputs.engineering

    scope = staticmethod(CycleInputReader.scope)

    def composition(self) -> tuple[object, ...]:
        require_acceptance(
            self.factory is self.inputs.factory
            and self.catalog is self.inputs.catalog
            and self.rules is self.inputs.rules
            and self.artifacts is self.inputs.artifacts
            and self.freshness is self.inputs.freshness
            and self.blobs is self.inputs.blobs
            and self.engineering is self.inputs.engineering
        )
        return self.inputs.composition()

    def require_composition(self, original: tuple[object, ...]) -> None:
        self.composition()
        self.inputs.require_composition(original)

    async def _author(
        self,
        session: AsyncSession,
        control: CompanyControl,
        proof: CurrentEngineeringProof,
        rule: CycleArtifactRule,
        action_id: UUID,
    ) -> tuple[ActionReceipt, ActionProposal]:
        author, _, _ = await self.inputs._pair(session, control, proof, rule)
        record = await session.get(JournalAction, action_id)
        require_acceptance(record is not None)
        assert record is not None
        action = ActionProposal.model_validate_json(record.proposal_json)
        decode_cycle_action(
            action,
            expected_kind=rule.kind,
            phase="write",
            binding=native_author(author)[0],
            permission=self.rules.rule(rule.kind, "write").permission,
        )
        issued = await require_cycle_publication_intent_locked(session, author, action, record)
        receipt = await actual_receipt(session, author, action_id)
        require_acceptance(issued.effect.state == "succeeded" and len(receipt.artifacts) == 2)
        return receipt, action

    async def _references(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        rule: CycleArtifactRule,
        action_id: UUID,
        receipt: ActionReceipt,
    ) -> tuple[ArtifactRevisionRef, ...]:
        # Namespace, bounded metadata, policy and receipt chronology are one read-only gate.
        result = []
        write = self.rules.rule(rule.kind, "write")
        for part, reference in zip(write.parts, receipt.artifacts, strict=True):
            key = uuid5(scope.company_id, f"cycle-deliverable:{rule.kind}:{action_id}:{part}")
            require_acceptance(
                (reference.company_id, reference.artifact_id, reference.revision)
                == (scope.company_id, key, f"stockflow-{rule.kind}-{part}-v1")
            )
            rows = tuple(
                (
                    await session.execute(
                        select(
                            BrainArtifactRevision.artifact_revision_id,
                            BrainArtifactRevision.sha256,
                            BrainArtifactRevision.byte_length,
                            BrainArtifactRevision.resource_id,
                            BrainArtifactRevision.media_type,
                            BrainArtifactRevision.storage_symbol,
                            BrainArtifactRevision.data_classification,
                            BrainArtifactRevision.recorded_at,
                        ).where(
                            BrainArtifactRevision.company_id == scope.company_id,
                            BrainArtifactRevision.artifact_id == key,
                            BrainArtifactRevision.revision == reference.revision,
                        )
                    )
                ).all()
            )
            require_acceptance(len(rows) == 1)
            row = rows[0]
            policy = write.policy(part)
            require_acceptance(
                row[0] == uuid5(key, "revision:v1")
                and row[1] == reference.sha256
                and 0 < row[2] <= policy.max_bytes
                and row[3] == write.target.resource_id
                and row[4] == policy.media_type
                and row[5] == self.blobs.storage_symbol
                and row[6] == policy.data_classification
                and row[7] <= receipt.recorded_at <= await db_now(session)
            )
            result.append(
                ArtifactRevisionRef(
                    company_id=scope.company_id,
                    artifact_id=key,
                    artifact_revision_id=row[0],
                    revision=reference.revision,
                    sha256=row[1],
                    byte_length=row[2],
                )
            )
        return tuple(result)

    async def _command_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        prepared: outputs.PreparedCycleDeliverable,
        proof: CurrentEngineeringProof,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> tuple[CycleArtifactCheckInput, ActionReceipt, CycleReadProtection]:
        # Native author chronology, current own proof and exact output references stay one phase.
        rule = self.rules.bind(work)
        require_acceptance(
            rule.phase == "check" and native_author(work)[0] == prepared.basis.verifier
        )
        current = await self.inputs._basis_locked(
            session,
            control,
            work,
            lease,
            identity,
            prepared.action_id,
            proof,
            credential=credential,
            observed_at=prepared.basis.observed_at,
        )
        require_acceptance(current.prepared == prepared)
        receipt, action = await self._author(session, control, proof, rule, prepared.action_id)
        scope = self.scope(lease, identity, prepared.action_id)
        refs = await self._references(session, scope, rule, prepared.action_id, receipt)
        require_acceptance(refs == tuple(row.artifact for row in prepared.manifest.parts))
        write = self.rules.rule(rule.kind, "write")
        require_author_action_pins(prepared, action, write)
        for ref in refs:
            await self.artifacts.revalidate_artifact_reference(
                session, control, scope, identity, ref, await db_now(session)
            )
        await require_author_replay_locked(
            session, scope, prepared, write, self.blobs.storage_symbol
        )
        original = prepared.basis.inputs
        inputs, classification = await native_manifest(
            session,
            scope,
            (*original.artifacts, *refs),
            original.contributors,
            original.evidence,
            original.required_resource_ids,
        )
        require_acceptance(
            CLASSIFICATIONS.index(rule.policy("check").data_classification)
            >= CLASSIFICATIONS.index(classification)
        )
        target = VerificationSpec(
            company_id=lease.company_id,
            author=prepared.basis.author,
            verifier=prepared.basis.verifier,
            action_id=prepared.action_id,
            proposal_sha256=receipt.proposal_hash,
            receipt_id=receipt.receipt_id,
            receipt_sha256=canonical_sha256(receipt),
            work_snapshot_sha256=prepared.basis.author_registration_sha256,
            criterion_ids=criteria_for(rule.kind),
            artifacts=refs,
            check_recipe=rule.recipe_version,
        )
        command = CycleArtifactCheckInput(
            company_id=lease.company_id,
            artifact_kind=rule.kind,
            target=target,
            original=prepared.basis,
            manifest=prepared.manifest,
            inputs=inputs,
            typed_json=prepared.typed_json,
            human_export=prepared.human_export,
        )
        protection = await self.inputs._capture(session, scope, proof, inputs, self.composition())
        current.protection.require_same_scope(protection)
        return command, receipt, protection

    async def prepare_check(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        author_action_id: UUID,
        check_action_id: UUID,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> CycleCheckMaterial:
        # Retain the first native windows across both unlocked complete-body reads and final gate.
        self.inputs._lease_rule(lease, identity, "check")
        require_acceptance(author_action_id != check_action_id)
        composition = self.composition()
        proof = await self.engineering.load(lease, identity, credential=credential)
        self.require_composition(composition)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work, _, _ = await self.engineering._actor(
                session, control, lease, identity, credential
            )
            rule = self.rules.bind(work)
            initial = await self.inputs._basis_locked(
                session,
                control,
                work,
                lease,
                identity,
                author_action_id,
                proof,
                credential=credential,
            )
            receipt, _ = await self._author(session, control, proof, rule, author_action_id)
            refs = await self._references(
                session,
                self.scope(lease, identity, author_action_id),
                rule,
                author_action_id,
                receipt,
            )
            self.require_composition(composition)
        bodies = []
        async with asyncio.timeout(BODY_READ_SECONDS):
            for ref in refs:
                bodies.append(
                    await load_complete_engineering_body(
                        self.artifacts,
                        self.freshness,
                        self.scope(lease, identity, author_action_id),
                        identity,
                        ref,
                    )
                )
                self.require_composition(composition)
        model = PresentationBrief if rule.kind == "presentation" else SupportDraft
        payload = model.model_validate_json(bodies[0].raw)
        prepare = (
            outputs.prepare_presentation if rule.kind == "presentation" else outputs.prepare_support
        )
        prepared = prepare(payload.basis, author_action_id)
        require_acceptance(
            (prepared.typed_json, prepared.human_export) == tuple(body.raw for body in bodies)
            and tuple(row.artifact for row in prepared.manifest.parts) == refs
        )
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work, _, _ = await self.engineering._actor(
                session, control, lease, identity, credential
            )
            command, receipt, protection = await self._command_locked(
                session, control, work, lease, identity, prepared, proof, credential=credential
            )
            initial.protection.require_same_scope(protection)
            protection = replace(initial.protection, bodies=tuple(bodies))
            result = CycleCheckMaterial(
                prepared,
                receipt,
                command,
                prepare_registered_cycle_check(command, check_action_id, rule),
                proof,
                protection,
            )
            await self.revalidate_check_locked(
                session, control, work, lease, identity, result, credential=credential
            )
            self.require_composition(composition)
            return result

    async def revalidate_check_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        material: CycleCheckMaterial,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> CycleReadProtection:
        rule = self.inputs._lease_rule(lease, identity, "check")
        self.require_composition(material.protection.composition)
        command, receipt, current = await self._command_locked(
            session,
            control,
            work,
            lease,
            identity,
            material.author,
            material.engineering,
            credential=credential,
        )
        require_acceptance(
            command == material.command
            and receipt == material.author_receipt
            and material.prepared
            == prepare_registered_cycle_check(command, material.prepared.action_id, rule)
            and material.engineering == material.protection.engineering
            and len(material.protection.bodies) == 2
            and tuple(body.first.artifact for body in material.protection.bodies)
            == command.target.artifacts
            and tuple(body.raw for body in material.protection.bodies)
            == (material.author.typed_json, material.author.human_export)
        )
        for body in material.protection.bodies:
            body.require_integrity()
            await revalidate_complete_engineering_artifact_locked(
                self.artifacts,
                session,
                control,
                self.scope(lease, identity, material.prepared.action_id),
                identity,
                body.first,
                await db_now(session),
            )
            await self.freshness.revalidate(
                session,
                self.scope(lease, identity, material.prepared.action_id),
                body.freshness,
                await db_now(session),
            )
        material.protection.require_same_scope(current)
        final = await db_now(session)
        self.require_composition(material.protection.composition)
        require_lease(work, lease, final, execute=True)
        material.protection.require_time(final)
        current.require_time(final)
        return current
