"""Own P/C input preparation; retained native READ windows confer no publication permit."""

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.engineering_bodies import revalidate_complete_engineering_artifact_locked
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.cycle_artifacts.citations import quote_sources
from nexus.company.cycle_artifacts.common import CycleKind
from nexus.company.cycle_artifacts.contracts import CycleArtifactBasis
from nexus.company.cycle_artifacts.engineering_prerequisite_reader import CycleEngineeringReader
from nexus.company.cycle_artifacts.native_contracts import (
    CurrentEngineeringProof,
    require_matching_composition,
)
from nexus.company.cycle_artifacts.production import (
    prepare_presentation,
    prepare_support,
)
from nexus.company.cycle_artifacts.publication_contracts import (
    CycleArtifactRule,
    CycleAuthorMaterial,
    CyclePhase,
    CyclePublicationRules,
    CycleReadProtection,
    require_author_output_bounds,
)
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_targets import current_work
from nexus.company.management.check_contracts import CitationCheckSource
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.native_report_inputs import CLASSIFICATIONS, native_manifest
from nexus.company.management.plan_admission_metadata import capture_grants, capture_sources
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_input_contracts import native_author
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now, lease_scope, require_lease, runtime_transaction
from nexus.harness.journal_models import CompanyControl


class CycleInputReader:
    def __init__(self, engineering: CycleEngineeringReader, rules: CyclePublicationRules) -> None:
        require_acceptance(
            type(engineering) is CycleEngineeringReader
            and type(rules) is CyclePublicationRules
            and engineering.catalog is rules.catalog
            and engineering.freshness._policies is rules.policies
        )
        self.engineering, self.rules = engineering, rules
        self.factory, self.catalog = engineering.factory, engineering.catalog
        self.artifacts, self.freshness = engineering.artifacts, engineering.freshness
        self.blobs = engineering.strategy.blobs
        self.composition()

    def composition(self) -> tuple[object, ...]:
        require_acceptance(
            self.factory is self.engineering.factory
            and self.catalog is self.engineering.catalog
            and self.catalog is self.rules.catalog
            and self.artifacts is self.engineering.artifacts
            and self.freshness is self.engineering.freshness
            and self.blobs is self.artifacts.blobs
            and self.rules.policies is self.freshness._policies
        )
        underlying = self.engineering.composition()
        return (
            self.engineering,
            self.rules,
            *underlying[:-1],
            (underlying[-1], self.rules.fingerprint()),
        )

    def require_composition(self, original: tuple[object, ...]) -> None:
        require_matching_composition(self.composition(), original)

    @staticmethod
    def scope(lease: ExecutionLease, identity: VerifiedIdentity, action_id: UUID) -> BrainReadScope:
        require_acceptance(
            (lease.actor_id, lease.workspace_id) == (identity.principal_id, identity.workspace_id)
        )
        return BrainReadScope(
            company_id=lease.company_id,
            workspace_id=lease.workspace_id,
            principal_id=identity.principal_id,
            operation_id=uuid5(action_id, "cycle-publication:v1"),
            trace_id=lease.trace_id,
            task_id=lease.task_id,
            task_trace_id=lease.trace_id,
            actor_id=lease.actor_id,
        )

    def _lease_rule(
        self, lease: ExecutionLease, identity: VerifiedIdentity, phase: CyclePhase
    ) -> CycleArtifactRule:
        self.scope(lease, identity, lease.segment_id)
        admission = self.catalog.cycle_admission
        require_acceptance(admission is not None and lease.company_id == self.catalog.company_id)
        assert admission is not None
        slots = tuple(
            row
            for row in admission.slots[4:8]
            if (
                row.child.binding.task_id,
                row.child.binding.trace_id,
                row.child.binding.run_id,
                row.child.binding.actor_id,
                row.child.binding.workspace_id,
                row.child.binding.workflow_version,
            )
            == (
                lease.task_id,
                lease.trace_id,
                lease.run_id,
                lease.actor_id,
                lease.workspace_id,
                lease.workflow_version,
            )
        )
        require_acceptance(
            len(slots) == 1 and slots[0].role.endswith("_check") == (phase == "check")
        )
        kind: CycleKind = (
            "presentation" if slots[0].role in {"presentation", "presentation_check"} else "support"
        )
        return self.rules.rule(kind, phase)

    async def _pair(
        self,
        session: AsyncSession,
        control: CompanyControl,
        proof: CurrentEngineeringProof,
        rule: CycleArtifactRule,
    ) -> tuple[ExecutionWork, RunBinding, RunBinding]:
        plan = proof.material.facts.plan
        admission = self.catalog.cycle_admission
        assert admission is not None
        offset = 4 if rule.kind == "presentation" else 6
        first, second = admission.slots[offset : offset + 2]
        author, child, _ = await current_work(
            session, control, plan.payload, plan.plan_revision_id, first.work.task_id
        )
        _, verifier, _ = await current_work(
            session, control, plan.payload, plan.plan_revision_id, second.work.task_id
        )
        require_acceptance(
            child.binding == first.child.binding and verifier.binding == second.child.binding
        )
        return author, child.binding, verifier.binding

    async def _manifest(
        self, session: AsyncSession, scope: BrainReadScope, proof: CurrentEngineeringProof
    ) -> tuple[GeneratedArtifactInputs, str]:
        strategy = proof.strategy.original.prepared
        original = strategy.original.snapshot.inputs
        values = (
            *original.artifacts,
            strategy.compiled.original_bundle.artifact,
            strategy.brief,
            proof.strategy.verifier.protected_result,
            *(body.first.artifact for body in proof.material.bodies),
        )
        refs = {row.artifact_revision_id: row for row in values}
        sources = {row.source_revision_id: row for row in original.contributors}
        for body in proof.material.bodies:
            sources.update({row.source_revision_id: row for row in body.first.source_contributors})
        manifest, classification = await native_manifest(
            session,
            scope,
            tuple(refs[key] for key in sorted(refs)),
            tuple(sources[key] for key in sorted(sources)),
            original.evidence,
            original.required_resource_ids,
        )
        require_acceptance(
            len(manifest.artifacts) <= 30
            and set(manifest.required_resource_ids) <= set(self.engineering.read_resources)
        )
        return manifest, classification

    async def _capture(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        proof: CurrentEngineeringProof,
        inputs: GeneratedArtifactInputs,
        composition: tuple[object, ...],
    ) -> CycleReadProtection:
        targets = tuple(
            sorted({self.rules.write_target.resource_id, self.rules.check_target.resource_id})
        )
        resources = tuple(sorted(set(inputs.required_resource_ids) | set(targets)))
        require_acceptance(len(resources) <= 32)
        now = await db_now(session)
        await require_resources(session, scope, resources, now)
        principals = {scope.principal_id}
        for key in targets:
            target = await session.get(BrainResource, (scope.company_id, key))
            require_acceptance(target is not None and target.active and target.kind == "artifact")
            rows = tuple(
                (
                    await session.scalars(
                        select(BrainResourceAccess).where(
                            BrainResourceAccess.company_id == scope.company_id,
                            BrainResourceAccess.resource_id == key,
                            BrainResourceAccess.active.is_(True),
                            or_(
                                BrainResourceAccess.expires_at.is_(None),
                                BrainResourceAccess.expires_at > now,
                            ),
                        )
                    )
                ).all()
            )
            require_acceptance(0 < len(rows) <= 32)
            for row in rows:
                member = await session.get(
                    DirectoryMembership, (scope.company_id, row.principal_id)
                )
                require_acceptance(
                    member is not None and member.principal_active and member.membership_active
                )
                principals.add(row.principal_id)
        pairs = tuple(
            sorted((resource, principal) for resource in resources for principal in principals)
        )
        grants = await capture_grants(session, scope, pairs, now)
        sources = await capture_sources(session, scope, resources, self.freshness, now)
        result = CycleReadProtection(
            proof, grants, tuple(row.qualified for row in sources), sources, now, composition
        )
        result.require_time(await db_now(session))
        return result

    async def _basis_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        proof: CurrentEngineeringProof,
        *,
        credential: AuthenticatedWorkerIdentity,
        observed_at: datetime | None = None,
    ) -> CycleAuthorMaterial:
        # Keep own identity, native closure and the final clock in one bounded phase.
        composition = self.composition()
        rule = self.rules.bind(work)
        self._lease_rule(lease, identity, rule.phase)
        await self.engineering.revalidate_locked(
            session, control, work, lease, identity, proof, credential=credential
        )
        author, binding, verifier = await self._pair(session, control, proof, rule)
        scope = self.scope(lease, identity, action_id)
        inputs, classification = await self._manifest(session, scope, proof)
        protection = await self._capture(session, scope, proof, inputs, composition)
        for reference in inputs.artifacts:
            await self.artifacts.revalidate_artifact_reference(
                session, control, scope, identity, reference, await db_now(session)
            )
        plan, original = (
            proof.material.facts.plan,
            proof.strategy.original.prepared.original.snapshot,
        )
        now = observed_at if observed_at is not None else await db_now(session)
        citations = tuple(
            CitationCheckSource.model_validate(row.model_dump(warnings=False))
            for row in original.sources
        )
        write = self.rules.rule(rule.kind, "write")
        output_class = write.policy("json").data_classification
        require_acceptance(output_class != "public")
        assert output_class != "public"
        require_acceptance(
            CLASSIFICATIONS.index(output_class) >= CLASSIFICATIONS.index(classification)
        )
        basis = CycleArtifactBasis(
            company_id=lease.company_id,
            artifact_kind=rule.kind,
            goal=plan.payload.goal,
            producing_plan=PlanRevisionRef.model_validate(
                plan.model_dump(include=set(PlanRevisionRef.model_fields))
            ),
            procedure_id=plan.payload.procedure.procedure_id,
            author=binding,
            verifier=verifier,
            author_registration=native_author(author)[1],
            author_registration_sha256=author.registration_hash,
            observed_at=now,
            engineering=proof.material.basis,
            inputs=inputs,
            citations=quote_sources(citations, now),
            target=write.target,
            data_classification=output_class,
        )
        prepare = prepare_presentation if rule.kind == "presentation" else prepare_support
        prepared = prepare(basis, action_id)
        require_author_output_bounds(prepared, write)
        require_acceptance(
            sum(row.byte_length for row in inputs.artifacts)
            + len(prepared.typed_json)
            + len(prepared.human_export)
            + self.rules.rule(rule.kind, "check").policy("check").max_bytes
            <= 8650752
        )
        for body in proof.material.bodies:
            await revalidate_complete_engineering_artifact_locked(
                self.artifacts, session, control, scope, identity, body.first, await db_now(session)
            )
        final = await db_now(session)
        self.require_composition(composition)
        require_lease(work, lease, final, execute=True)
        require_acceptance(lease.expires_at > final)
        protection.require_time(final)
        return CycleAuthorMaterial(prepared, proof, protection)

    async def prepare_author(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> CycleAuthorMaterial:
        self._lease_rule(lease, identity, "write")
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
            material = await self._basis_locked(
                session, control, work, lease, identity, action_id, proof, credential=credential
            )
            self.require_composition(composition)
            return material

    async def revalidate_author_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        material: CycleAuthorMaterial,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> CycleReadProtection:
        self._lease_rule(lease, identity, "write")
        self.require_composition(material.protection.composition)
        current = await self._basis_locked(
            session,
            control,
            work,
            lease,
            identity,
            material.prepared.action_id,
            material.engineering,
            credential=credential,
            observed_at=material.prepared.basis.observed_at,
        )
        require_acceptance(
            current.prepared == material.prepared
            and native_author(work)[0] == material.prepared.basis.author
            and material.engineering == material.protection.engineering
        )
        material.protection.require_same_scope(current.protection)
        final = await db_now(session)
        self.require_composition(material.protection.composition)
        material.protection.require_time(final)
        current.protection.require_time(final)
        return current.protection
