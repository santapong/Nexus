"""Dormant P/C prerequisite READ; own signed lease, immutable E/EV evidence, no effect wiring."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.engineering_bodies import revalidate_complete_engineering_artifact_locked
from nexus.builder.engineering_contracts import EngineeringChangeDeclaration
from nexus.builder.engineering_proof import EngineeringProofStorage
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import RegisteredBuilderSource
from nexus.builder.verification_support import (
    actual_result_reference,
    require_containment_configuration,
    require_result_containment,
)
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.cycle_artifacts import native_contracts as contracts
from nexus.company.cycle_artifacts.engineering_prerequisite_facts import (
    read_engineering_prerequisite_locked,
)
from nexus.company.cycle_artifacts.engineering_prerequisite_material import (
    load_engineering_material,
    require_engineering_material,
)
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_admission_candidates import capture_child_window
from nexus.company.management.plan_admission_metadata import capture_grants, capture_sources
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.strategy_transition_observation import validate_transition_proof
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.current_proof_read import (
    StrategyProofMaterial,
    assemble_strategy_current_proof,
    read_strategy_proof_material_locked,
)
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_protection import require_credential
from nexus.execution.cycle_deliverable_partition import require_cycle_deliverable_partition_locked
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)
from nexus.harness.journal_models import CompanyControl


class CycleEngineeringReader:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
        results: BuilderResultStore,
        declarations: tuple[EngineeringChangeDeclaration, ...],
        source: RegisteredBuilderSource,
        proof: EngineeringProofStorage,
        summary_policy: SourcePolicy,
        strategy: StrategyInputReader,
        read_resources: tuple[UUID, ...],
        *,
        containment_store: ContainmentEvidenceStore | None = None,
        execution_method_sha256: str | None = None,
    ) -> None:
        require_containment_configuration(containment_store, execution_method_sha256)
        require_acceptance(
            artifacts.factory is factory is freshness._factory
            and artifacts is strategy.artifacts
            and artifacts.blobs is proof.blobs
            and freshness._policies is strategy.policies
            and canonical_sha256(catalog) == canonical_sha256(strategy.catalog)
            and 0 < len(declarations) <= 32
            and len({row.goal_id for row in declarations}) == len(declarations)
            and all(row.company_id == catalog.company_id for row in declarations)
            and proof.target.company_id == source.metadata.company_id == catalog.company_id
            and source.metadata.byte_length <= 16384
            and 0 < len(read_resources) <= 32
            and len(set(read_resources)) == len(read_resources)
            and set(read_resources) <= {row.resource.resource_id for row in catalog.resources}
        )
        self.factory, self.catalog, self.artifacts, self.freshness = (
            factory,
            catalog,
            artifacts,
            freshness,
        )
        self.results, self.source, self.proof, self.summary_policy, self.strategy = (
            results,
            source,
            proof,
            summary_policy,
            strategy,
        )
        self.declarations = {row.goal_id: row for row in declarations}
        self.read_resources = tuple(sorted(read_resources))
        self.containment_store, self.execution_method_sha256 = (
            containment_store,
            execution_method_sha256,
        )
        self.composition()

    def composition(self) -> tuple[object, ...]:
        return contracts.cycle_engineering_composition(self)

    def require_composition(self, original: tuple[object, ...]) -> None:
        contracts.require_matching_composition(self.composition(), original)

    scope = staticmethod(contracts.cycle_engineering_scope)

    async def _actor(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        credential: AuthenticatedWorkerIdentity,
    ) -> tuple[ExecutionWork, PlanRevision, BrainReadScope]:
        scope = self.scope(lease, identity)
        await require_strategy_application_role(session)
        work = await execution_row(session, lease_scope(lease))
        now = await db_now(session)
        require_acceptance(lease.expires_at > now)
        require_lease(work, lease, now, execute=True)
        require_credential(credential, identity, scope, await db_now(session))
        require_acceptance(
            self.catalog.cycle_admission is not None
            and self.catalog.models.pricebook_version == control.price_version
        )
        assert self.catalog.cycle_admission is not None
        plan = await require_cycle_deliverable_partition_locked(
            session,
            control,
            work,
            identity,
            admission=self.catalog.cycle_admission,
            registry=self.catalog.models,
        )
        await require_brain_scope(session, control, scope, identity)
        return work, plan, scope

    async def _observe(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        credential: AuthenticatedWorkerIdentity,
    ) -> tuple[
        contracts.EngineeringPrerequisiteFacts,
        contracts.CycleEngineeringReadProtection,
        StrategyProofMaterial,
    ]:
        work, plan, scope = await self._actor(session, control, lease, identity, credential)
        observed = await db_now(session)
        profiles = tuple(
            capture_child_window(self.catalog, child, observed) for child in plan.payload.children
        )
        grants = await require_resources(session, scope, self.read_resources, observed)
        grant_rows = await capture_grants(
            session,
            scope,
            tuple((key, identity.principal_id) for key in self.read_resources),
            observed,
        )
        source_rows = await capture_sources(
            session, scope, self.read_resources, self.freshness, observed
        )
        protection = contracts.CycleEngineeringReadProtection(
            observed,
            tuple(row.qualified for row in source_rows),
            grants,
            credential,
            lease,
            self.catalog,
            plan.payload.children,
            profiles,
            (control.policy_version, control.price_version),
            grant_rows,
            source_rows,
        )
        facts = await read_engineering_prerequisite_locked(
            session,
            control,
            work,
            scope,
            identity,
            plan=plan,
            catalog=self.catalog,
            artifacts=self.artifacts,
            freshness=self.freshness,
            credential=credential,
            source=self.source,
            proof=self.proof,
            summary_policy=self.summary_policy,
        )
        patch = facts.metadata.author_spec.protected_patch
        assert patch is not None
        refs = (
            facts.metadata.author_output,
            facts.metadata.verifier_output,
            facts.check,
            patch,
            self.source.metadata,
        )
        ids, resources = await reference_sources(session, scope, refs)
        require_acceptance(
            set(resources) <= set(self.read_resources)
            and set(ids) <= {row.source_id for row in source_rows}
        )
        selection = plan.payload.strategy_selection
        require_acceptance(selection is not None)
        assert selection is not None
        strategy = await read_strategy_proof_material_locked(
            self.strategy, session, control, scope, identity, selection, credential
        )
        protection.require_time(await db_now(session))
        return facts, protection, strategy

    async def load(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> contracts.CurrentEngineeringProof:
        original, catalog_sha = self.composition(), canonical_sha256(self.catalog)
        scope = self.scope(lease, identity)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            facts, initial, first_strategy = await self._observe(
                session, control, lease, identity, credential
            )
        self.require_composition(original)
        material = await load_engineering_material(self, scope, identity, facts)
        self.require_composition(original)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            current_facts, current, strategy = await self._observe(
                session, control, lease, identity, credential
            )
            require_acceptance(current_facts == facts)
            selection = facts.plan.payload.strategy_selection
            assert selection is not None
            selected = assemble_strategy_current_proof(
                selection,
                first_strategy,
                strategy,
                credential,
                scope,
                identity,
                await db_now(session),
            )
            candidate = validate_transition_proof(facts.plan.payload, self.catalog, selected)
            require_acceptance(
                candidate.kind == "change"
                and candidate.patch_sha256 == material.basis.patch_sha256
                and selected.brief.repository == material.basis.source
            )
            result = contracts.CurrentEngineeringProof(
                material, selected, initial, current, original, catalog_sha
            )
            await self.revalidate_locked(
                session,
                control,
                await execution_row(session, lease_scope(lease)),
                lease,
                identity,
                result,
                credential=credential,
            )
            return result

    async def revalidate_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        proof: contracts.CurrentEngineeringProof,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> None:
        require_engineering_material(self, proof.material)
        require_acceptance(proof.initial.credential is credential and proof.initial.lease == lease)
        actual, _, scope = await self._actor(session, control, lease, identity, credential)
        require_acceptance(actual is work)
        facts, current, first = await self._observe(session, control, lease, identity, credential)
        require_acceptance(
            facts == proof.material.facts
            and current.grants == proof.initial.grants
            and current.grant_rows == proof.initial.grant_rows
            and current.source_rows == proof.initial.source_rows
            and current.versions == proof.initial.versions
        )
        for result, reference in (
            (proof.material.command.author, facts.metadata.author_output),
            (proof.material.command.verifier, facts.metadata.verifier_output),
        ):
            require_acceptance(await actual_result_reference(session, result) == reference)
            await require_result_containment(
                result, self.containment_store, self.execution_method_sha256
            )
        for body in proof.material.bodies:
            body.require_integrity()
            await revalidate_complete_engineering_artifact_locked(
                self.artifacts, session, control, scope, identity, body.first, await db_now(session)
            )
            await self.freshness.revalidate(session, scope, body.freshness, await db_now(session))
        selection = facts.plan.payload.strategy_selection
        assert selection is not None
        second = await read_strategy_proof_material_locked(
            self.strategy, session, control, scope, identity, selection, credential
        )
        strategy = assemble_strategy_current_proof(
            selection, first, second, credential, scope, identity, await db_now(session)
        )
        require_acceptance(
            (
                strategy.original,
                strategy.acceptance,
                strategy.brief,
                strategy.verifier,
                strategy.check_result,
                strategy.author_current_fence,
                strategy.verifier_current_fence,
            )
            == (
                proof.strategy.original,
                proof.strategy.acceptance,
                proof.strategy.brief,
                proof.strategy.verifier,
                proof.strategy.check_result,
                proof.strategy.author_current_fence,
                proof.strategy.verifier_current_fence,
            )
        )
        actual, _, _ = await self._actor(session, control, lease, identity, credential)
        final = await db_now(session)
        self.require_composition(proof.composition)
        require_acceptance(canonical_sha256(self.catalog) == proof.catalog_sha256)
        require_lease(actual, lease, final, execute=True)
        proof.require_time(final)
        current.require_time(final)
        strategy.require_time(final)
