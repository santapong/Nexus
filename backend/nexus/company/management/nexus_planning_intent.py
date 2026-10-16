"""Original genuine planner witness around actual planning/context checks; no permission DTO."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.nexus_coding_catalog import select_configured_nexus_plan
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.management.planning_intent import PlanningIntentCheck
from nexus.company.management.revision_store import plan_record
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


class NexusPlanningIntentCheck(PlanningIntentCheck):
    def __init__(
        self,
        original: PlanningIntentCheck,
        credential: AuthenticatedWorkerIdentity,
        *,
        catalog: PlanAdmissionCatalog | None = None,
    ) -> None:
        if type(original) is not PlanningIntentCheck or not isinstance(
            credential, AuthenticatedWorkerIdentity
        ):
            raise ValueError("Nexus planning needs its actual check and authenticated actor")
        super().__init__(original._context_check, original._prepared, registry=original.registry)
        self.credential = credential
        self._original = original
        self._catalog = catalog
        self._objects = (
            original,
            original._prepared,
            self._context_check,
            self._prepared,
            credential,
            self._context_check._revalidator,
            catalog,
            *self._coding_graph(),
        )
        self._pins = self.fingerprint()
        self.require_composition()

    @property
    def factory(self) -> async_sessionmaker[AsyncSession]:
        checker = self._context_check
        if type(checker._revalidator) is not PersistentContextAssembler:
            raise ValueError("Nexus planning requires the real context assembler")
        return checker._revalidator._factory

    def fingerprint(self) -> tuple[object, ...]:
        check = self._context_check
        return (
            self._prepared.model_dump_json(by_alias=True),
            check._lease,
            check._identity,
            check._scope,
            check._request,
            check._recipe,
            check._classification,
            self.credential.identity,
            self.credential.issued_at,
            self.credential.expires_at,
            self.factory,
            self.registry,
            canonical_sha256(self._catalog) if self._catalog is not None else None,
        )

    def _coding_graph(self) -> tuple[object, ...]:
        """New-profile L retains the actual management authority and protected source graph."""
        if self._catalog is None or self._catalog.nexus_coding_admission is None:
            return ()
        assembler = self._context_check._revalidator
        if type(assembler) is not PersistentContextAssembler:
            raise ValueError("Coding planner requires its actual context assembler")
        authority, retriever = assembler._authority, assembler._retriever
        if (
            type(authority) is not ManagementPlanningAuthority
            or type(retriever) is not PersistentBrainRetriever
        ):
            raise ValueError("Coding planner requires its actual management context authority")
        management = authority.management
        if (
            management.catalog is not self._catalog
            or authority.recipe != self._context_check._recipe
            or (
                authority.policy.workflow_name,
                authority.policy.workflow_version,
                authority.policy.model_profile,
            )
            != ("company.planning.v1", "v1", "reasoning")
            or type(management.artifacts) is not BoundedArtifactReader
            or type(management.freshness) is not RegisteredSourceFreshness
            or type(retriever.blobs) is not ProtectedBlobStore
            or management.artifacts.blobs is not retriever.blobs
            or management.artifacts.factory is not self.factory
            or management.freshness._factory is not self.factory
            or retriever.factory is not self.factory
        ):
            raise ValueError("Coding planner original protected authority graph differs")
        authority._require_original()
        return (
            authority,
            management,
            management.artifacts,
            management.freshness,
            retriever,
            retriever.blobs,
        )

    def require_composition(self) -> None:
        check = self._context_check
        if (
            type(check) is not BrainModelContextCheck
            or any(
                a is not b
                for a, b in zip(
                    self._objects,
                    (
                        self._original,
                        self._original._prepared,
                        check,
                        self._prepared,
                        self.credential,
                        check._revalidator,
                        self._catalog,
                        *self._coding_graph(),
                    ),
                    strict=True,
                )
            )
            or self.fingerprint() != self._pins
        ):
            raise ValueError("Nexus planning original composition changed")
        if (
            self._original._context_check is not check
            or self._original._prepared != self._prepared
            or check._identity != self.credential.identity
            or check._lease.expires_at > self.credential.expires_at
        ):
            raise ValueError("Nexus planning credential does not cover its own original lease")
        if (
            self.registry is None
            or self._prepared.input_estimate is None
            or self._prepared.input_estimate.whole_request is None
        ):
            raise ValueError("Fresh Nexus planning requires its real whole-input proof")
        check._require_snapshot_binding()

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        self.validate_time(now)
        await super().validate(session, control, work, action, now)
        if self._catalog is not None and self._catalog.nexus_coding_admission is not None:
            row = await session.get(
                ManagementPlanRevision,
                (
                    control.company_id,
                    self._prepared.binding.expected_plan_revision_id,
                ),
            )
            if row is None:
                raise ValueError("Coding planner requires its actual persisted native plan")
            record = plan_record(row)
            if record.sha256 != canonical_sha256(record.payload):
                raise ValueError("Coding planner native payload digest changed")
            select_configured_nexus_plan(self._catalog, record.payload)
        self.validate_time(await db_now(session))

    def validate_time(self, now: datetime) -> None:
        self.require_composition()
        self.credential.require_time(now)
        manifest = self._prepared.context.manifest
        deadlines = (
            self._context_check._lease.expires_at,
            *(grant.expires_at for grant in manifest.contributors),
            *(head.fresh_until for head in manifest.source_heads),
        )
        if any(end is not None and now >= end for end in deadlines):
            raise ValueError("Nexus planning original source/grant/lease window expired")


def nexus_planning_intent_shape(
    factory: async_sessionmaker[AsyncSession],
    catalog: PlanAdmissionCatalog,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    proposal: ActionProposal,
    check: BeforeIntentCheck | None,
) -> tuple[object, ...]:
    """Exact existing concrete L/Model/L chain, retained across every effect-boundary await."""
    from nexus.harness.model_authorizer_contracts import model_action_parameters
    from nexus.harness.model_input_estimator import FullContextInputEstimator
    from nexus.harness.model_intent import ModelIntentCheck

    if type(check) is not CompositeBeforeIntentCheck or len(check._checks) != 3:
        raise ValueError("Fresh Nexus planning needs its exact original composite")
    planning, model, repeated = check._checks
    if (
        type(planning) is not NexusPlanningIntentCheck
        or type(model) is not ModelIntentCheck
        or repeated is not planning
    ):
        raise ValueError("Fresh Nexus planning needs its exact original composite")
    planning.require_composition()
    if (
        planning.factory is not factory
        or planning._context_check._lease != lease
        or planning.credential.identity != identity
        or model.lease != lease
        or type(model.estimator) is not FullContextInputEstimator
        or planning.registry != model.registry
        or model.estimator.estimate(model.call, model.registry, model.recipe)
        != planning._prepared.input_estimate
        or model.call != planning._prepared.request
        or canonical_sha256(model.registry) != canonical_sha256(catalog.models)
        or proposal.parameters != model_action_parameters(model.call, model.recipe)
        or (catalog.nexus_coding_admission is not None and planning._catalog is not catalog)
    ):
        raise ValueError("Fresh Nexus planning original composition changed")
    return (
        check,
        planning,
        model,
        planning.credential,
        planning._objects,
        planning._pins,
        model.call,
        canonical_sha256(model.registry),
        model.recipe,
        model.estimator,
        model.observations,
    )
