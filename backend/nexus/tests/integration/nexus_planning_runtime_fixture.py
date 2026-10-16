"""Real public Nexus governance setup; synthetic model eligibility is NOT live quality.

The closed six-role description is reused only as unregistered configuration data.
Cohesion exception: the complete public-source/governance fixture stays in one helper.
Every goal/mandate/charter reference below is an actual public-store return. No fake
context authority, native receipt, builder, accepted result or SQL row seed is used.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope, SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.retrieval import RetrievalLimits, SearchRequest
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    EvidenceRef,
    IngestCommand,
    SourceRegistration,
)
from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.company.directory_contracts import CompanyRegistration, MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import (
    DueIntent,
    GoalDefinition,
    GoalMetric,
    GoalRevisionRef,
    UnknownBaseline,
)
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.nexus_cycle_admission import NexusCycleAdmission, NexusCycleSlot
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.management_services import ManagementExecutionServices
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import CompanyPolicy, LedgerScope
from nexus.harness.model_authorizer_contracts import ModelInputRecipe
from nexus.harness.model_input_estimator import (
    RECIPE_ID,
    RECIPE_REVISION,
    input_conformance_reference,
)
from nexus.tests.unit.nexus_cycle_fixture import COMPANY as NEXUS_FIXTURE_COMPANY
from nexus.tests.unit.nexus_cycle_fixture import case as descriptions

COMPANY: UUID = NEXUS_FIXTURE_COMPANY
DOCUMENT = "docs/company-system/ARCHITECTURE.md"
DOCUMENT_SHA256 = "52d926a42ece553c2ce412ee7ed2286d563499b85e59c717f74d4c7c8ee2faf7"
DOCUMENT_COMMIT = "f4ed4db2fb7a9c19b6322eda69bc93689b938c05"


def key(label: str) -> UUID:
    return uuid5(COMPANY, "nexus-planning-runtime-v4:" + label)


def owner_scope(admission: NexusCycleAdmission) -> CompanyControlScope:
    return CompanyControlScope(
        company_id=COMPANY,
        principal_id=admission.procedure.binding.actor_id,
        operation_id=key("owner-operation"),
        trace_id=key("owner-audit"),
    )


def brain_owner(admission: NexusCycleAdmission) -> BrainReadScope:
    control = owner_scope(admission)
    return BrainReadScope(
        company_id=COMPANY,
        workspace_id=admission.procedure.binding.workspace_id,
        principal_id=control.principal_id,
        operation_id=control.operation_id,
        trace_id=control.trace_id,
    )


async def bootstrap(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[NexusCycleAdmission, PersistentCompanyDirectory]:
    """Explicit operator mapping; subsequent actions use actual JWT identities."""
    admission, _ = descriptions()
    control = owner_scope(admission)
    await CompanyJournal(factory).create_company(
        CompanyPolicy(
            company_id=COMPANY,
            owner_id=control.principal_id,
            policy_version="nexus-planning-runtime-v1",
            price_version="p1",
        ),
        LedgerScope(
            company_id=COMPANY,
            principal_id=control.principal_id,
            task_id=control.operation_id,
            trace_id=control.trace_id,
        ),
    )
    directory = PersistentCompanyDirectory(factory)
    await directory.bootstrap(
        CompanyRegistration(
            company_id=COMPANY,
            workspace_id=admission.procedure.binding.workspace_id,
            owner_id=control.principal_id,
        ),
        control,
    )
    for actor in sorted(
        {slot.child.binding.actor_id for slot in admission.slots} - {control.principal_id}
    ):
        await directory.set_membership(
            MembershipChange(company_id=COMPANY, principal_id=actor, role="member"), control
        )
    return admission, directory


class DocumentReader:
    def __init__(self, registration: SourceRegistration, raw: bytes) -> None:
        self.registration, self.raw = registration, raw

    async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
        # SourceRecord is a strict superset; compare only the exact registration contract.
        actual = SourceRegistration.model_validate_json(
            source.model_dump_json(include=set(SourceRegistration.model_fields))
        )
        if actual != self.registration or revision != DOCUMENT_COMMIT:
            raise ValueError("Exact pinned Nexus document is unavailable")
        return SourceSnapshot(
            company_id=COMPANY,
            source_id=source.source_id,
            source_symbol=source.source_symbol,
            external_key=source.external_key,
            revision=revision,
            raw_bytes=self.raw,
            source_event=SourceTime(
                precision="unknown",
                value=None,
                basis="Committed SHA-pinned Nexus design document; not execution evidence",
            ),
        )


@dataclass(frozen=True)
class Governance:
    admission: NexusCycleAdmission
    catalog: PlanAdmissionCatalog
    management: ManagementExecutionServices
    retriever: PersistentBrainRetriever
    sources: OwnerViewSources
    registry: SourceRegistry
    blobs: ProtectedBlobStore
    controls: ManagementControlStore
    goals: GoalStore
    doc_resource: ResourceRef
    doc_evidence: EvidenceRef


def input_recipe() -> ModelInputRecipe:
    return ModelInputRecipe(
        recipe_id=RECIPE_ID,
        revision=RECIPE_REVISION,
        profile="reasoning",
        minimum_score=Decimal("0.8"),
        evaluation_suite_version="synthetic-nexus-component",
        conformance_reference=input_conformance_reference(),
    )


async def governance(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    initial: NexusCycleAdmission,
    owner: AuthenticatedWorkerIdentity,
) -> Governance:
    """Current owner creates actual source/goal/charters; no Work exists until explicit approval."""
    owner.require_time(datetime.now(UTC))
    assert owner.identity.principal_id == initial.procedure.binding.actor_id
    raw = await asyncio.to_thread((Path(__file__).resolve().parents[4] / DOCUMENT).read_bytes)
    assert len(raw) == 5933 and hashlib.sha256(raw).hexdigest() == DOCUMENT_SHA256
    assert b"Company Brain" in raw and b"Action Harness" in raw
    scope, brain = owner_scope(initial), brain_owner(initial)
    resource = ResourceRef(company_id=COMPANY, resource_id=key("documentation-resource"))
    source = SourceRegistration(
        company_id=COMPANY,
        source_id=key("documentation-source"),
        resource=resource,
        source_symbol="nexus.architecture.runtime.v1",
        external_key=DOCUMENT,
    )
    policy = SourcePolicy(
        source_symbol=source.source_symbol,
        authority_profile="nexus.committed-docs.v1",
        data_classification="internal",
        media_type="text/markdown",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=3600,
        allowed_external_keys=frozenset({DOCUMENT}),
    )
    registry = SourceRegistry((policy,), DocumentReader(source, raw))
    blobs = ProtectedBlobStore(root / "brain", storage_symbol="nexus.planning.runtime.brain.v1")
    ingestion = BrainIngestionStore(factory, registry, blobs)
    await ingestion.register(
        brain,
        owner.identity,
        source,
        readers=tuple(
            sorted(
                {
                    owner.identity.principal_id,
                    *(slot.child.binding.actor_id for slot in initial.slots),
                }
            )
        ),
    )
    artifact_id = key("documentation-artifact")
    ingested = await ingestion.ingest(
        brain,
        owner.identity,
        IngestCommand(
            company_id=COMPANY,
            source_id=source.source_id,
            revision=DOCUMENT_COMMIT,
            artifact=ArtifactRevisionRef(
                company_id=COMPANY,
                artifact_id=artifact_id,
                artifact_revision_id=uuid5(artifact_id, DOCUMENT_COMMIT),
                revision=DOCUMENT_COMMIT,
                sha256=DOCUMENT_SHA256,
                byte_length=len(raw),
            ),
        ),
    )
    assert ingested.status == "accepted"
    retriever = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    found = await retriever.search(
        brain, owner.identity, SearchRequest(company_id=COMPANY, query="Nexus")
    )
    assert found.handles
    evidence = EvidenceRef(company_id=COMPANY, evidence_id=found.handles[0].handle.evidence_id)
    controls = ManagementControlStore(factory)
    mandate = await controls.publish_mandate(
        scope,
        owner.identity,
        CompanyMandate(
            company_id=COMPANY,
            owner_id=owner.identity.principal_id,
            version="nexus-planning-runtime-v1",
            purpose=(
                "Review a Nexus-owned cited plan under supervised approval; no builder execution"
            ),
            goals=(initial.goal.goal_id,),
        ),
        expected_revision_id=None,
    )
    mref = RevisionRef.model_validate_json(
        mandate.model_dump_json(include=set(RevisionRef.model_fields))
    )
    goals = GoalStore(factory, retriever)
    goal = await goals.publish(
        scope,
        owner.identity,
        GoalDefinition(
            company_id=COMPANY,
            goal_id=initial.goal.goal_id,
            owner_id=owner.identity.principal_id,
            title="Make Nexus goal-to-plan review explicit without bypassing execution gates",
            mandate=mref,
            metrics=(
                GoalMetric(
                    company_id=COMPANY,
                    metric_id="owner.plans.reviewed",
                    unit="count",
                    comparator="ge",
                    target=Decimal(1),
                    baseline=UnknownBaseline(
                        reason="Architecture is design evidence, not a measured operating result",
                        evidence=(evidence,),
                    ),
                ),
            ),
            due=DueIntent(
                source_time=SourceTime(
                    precision="unknown", value=None, basis="No execution date supplied"
                )
            ),
        ),
        version="nexus-goal-v1",
        expected_revision_id=None,
    )
    gref = GoalRevisionRef.model_validate_json(
        goal.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    slots = []
    for index, slot in enumerate(initial.slots):
        verifier = (
            initial.slots[2].child.binding.actor_id
            if index == 1
            else initial.slots[1].child.binding.actor_id
            if index == 2
            else initial.slots[4].child.binding.actor_id
            if index in (3, 5)
            else initial.slots[3].child.binding.actor_id
            if index == 4
            else owner.identity.principal_id
        )
        charter = await controls.publish_charter(
            scope,
            owner.identity,
            DepartmentCharter(
                company_id=COMPANY,
                department_id=slot.child.charter.department_id,
                name=slot.role,
                version="v1",
                responsibilities=("Review Nexus evidence within the exact declared role",),
                allowed_tools=(slot.tool.tool,),
                resource_scopes=(slot.tool.resource, "nexus.knowledge"),
                deliverables=("Nexus " + slot.role + " outcome subject to native verification",),
                verifier_id=verifier,
            ),
            mandate=mref,
            expected_revision_id=None,
        )
        cref = CharterRevisionRef.model_validate_json(
            charter.model_dump_json(include=set(CharterRevisionRef.model_fields))
        )
        amount = Decimal("0.5") if index == 0 else Decimal("0.1")
        slots.append(
            NexusCycleSlot(
                role=slot.role,
                tool=slot.tool,
                child=slot.child.model_copy(update={"charter": cref, "allocation_usd": amount}),
                work=slot.work.model_copy(update={"budget_usd": amount}),
            )
        )
    # Fixed synthetic eligibility for this isolated fixture, not a live observation/promotion.
    _, seed = descriptions()
    now = datetime.now(UTC)
    model = seed.models.models[0]
    model = model.model_copy(
        update={
            "health": model.health.model_copy(update={"expires_at": now + timedelta(hours=1)}),
            "evaluations": tuple(
                row.model_copy(update={"expires_at": now + timedelta(hours=1)})
                for row in model.evaluations
            ),
        }
    )
    models = ModelRegistry.model_validate_json(
        seed.models.model_copy(update={"models": (model,)}).model_dump_json()
    )
    digest = canonical_sha256(models)
    admission = NexusCycleAdmission.model_validate(
        initial.model_dump()
        | {"goal": gref, "mandate": mref, "registry_sha256": digest, "slots": tuple(slots)}
    )
    resources = tuple(
        NamedPlanResource(symbol=symbol, resource=resource)
        for symbol in (*dict.fromkeys(slot.tool.resource for slot in slots), "nexus.knowledge")
    )
    catalog = PlanAdmissionCatalog.model_validate(
        seed.model_dump()
        | {
            "models": models,
            "resources": resources,
            "native_profiles": tuple(
                row.model_copy(update={"registry_sha256": digest}) for row in seed.native_profiles
            ),
            "notification_profiles": tuple(
                row.model_copy(update={"registry_sha256": digest, "target_resource": resource})
                for row in seed.notification_profiles
            ),
            "nexus_cycle_admission": admission,
        }
    )
    freshness = RegisteredSourceFreshness(factory, registry)
    artifacts = BoundedArtifactReader(factory, blobs)
    sources = OwnerViewSources(artifacts, freshness)
    owner.require_time(datetime.now(UTC))
    return Governance(
        admission,
        catalog,
        ManagementExecutionServices(catalog, artifacts, freshness),
        retriever,
        sources,
        registry,
        blobs,
        controls,
        goals,
        resource,
        evidence,
    )
