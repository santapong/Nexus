"""Actual native compiler/execution composition; no model, queue or provider startup."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.acceptance_evidence import ProtectedReportEvidenceResolver
from nexus.company.management.acceptance_freshness import (
    RegisteredSourceFreshness,
    RegisteredSourcePolicies,
)
from nexus.company.management.acceptance_recovery import AcceptanceRecovery
from nexus.company.management.acceptance_store import WorkAcceptanceStore
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactRule
from nexus.company.management.generated_artifact_store import GeneratedArtifactPublisher
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.native_report_validator import NativeReportValidator
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.management.scheduling_support import SchedulerIdentities, SchedulerResources
from nexus.company.notifications.receipt_event_publisher import NativeReceiptEventPublisher
from nexus.execution.effect_store import EffectStore
from nexus.execution.native_report_services import (
    NATIVE_APPLICATION,
    NATIVE_QUEUE,
    NATIVE_VERSION,
    NATIVE_WORKFLOW,
    NativeReportHook,
    NativeReportServices,
)
from nexus.execution.runtime_store import ExecutionStore


def compose_native_reports(
    factory: async_sessionmaker[AsyncSession],
    *,
    catalog: PlanAdmissionCatalog,
    blobs: BrainBlobStore,
    policies: RegisteredSourcePolicies,
    rules: tuple[GeneratedArtifactRule, ...],
    identities: SchedulerIdentities,
    resources: SchedulerResources,
    worker_id: UUID,
    hook: NativeReportHook | None = None,
    lease_ttl_seconds: int = 60,
    executor_id: str = "nexus-native-management-v1-local",
) -> NativeReportServices:
    """Use one trusted catalog/source policy/reader across compiler, intent, publisher and proof."""
    producer, publisher, artifacts, resolver = _native_compiler(
        factory, catalog, blobs, policies, rules
    )
    freshness = publisher.freshness
    execution, effects = _managed_stores(factory, catalog, artifacts, freshness)
    return NativeReportServices(
        factory=factory,
        execution=execution,
        effects=effects,
        producer=producer,
        publisher=publisher,
        acceptance=WorkAcceptanceStore(factory, resolver),
        recovery=AcceptanceRecovery(factory, resolver, producer),
        artifacts=artifacts,
        identities=identities,
        resources=resources,
        worker_id=worker_id,
        registration=WorkflowRegistration(
            workflow_name=NATIVE_WORKFLOW,
            workflow_version=NATIVE_VERSION,
            queue_name=NATIVE_QUEUE,
            application_name=NATIVE_APPLICATION,
        ),
        lease_ttl_seconds=lease_ttl_seconds,
        hook=hook,
        executor_id=executor_id,
    )


def _native_compiler(
    factory: async_sessionmaker[AsyncSession],
    catalog: PlanAdmissionCatalog,
    blobs: BrainBlobStore,
    policies: RegisteredSourcePolicies,
    rules: tuple[GeneratedArtifactRule, ...],
) -> tuple[
    NativeReportProducer,
    GeneratedArtifactPublisher,
    BoundedArtifactReader,
    ProtectedReportEvidenceResolver,
]:
    """Assemble the exact protected reader/compiler/publisher chain without activation."""
    artifacts = BoundedArtifactReader(factory, blobs)
    retriever = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    freshness = RegisteredSourceFreshness(factory, policies)
    reports = OperatingReportStore(factory, catalog, artifacts, freshness)
    inputs = PersistentReportInputLoader(
        factory,
        ReportArtifactReader(retriever, artifacts),
        reports,
        source_policies=policies,
    )
    producer = NativeReportProducer(factory, reports, inputs)
    publisher = GeneratedArtifactPublisher(
        factory,
        blobs,
        catalog,
        artifacts,
        policies,
        NativeReportValidator(producer),
        rules=rules,
    )
    resolver = ProtectedReportEvidenceResolver(artifacts, inputs, freshness)
    return producer, publisher, artifacts, resolver


def _managed_stores(
    factory: async_sessionmaker[AsyncSession],
    catalog: PlanAdmissionCatalog,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> tuple[ExecutionStore, EffectStore]:
    """Keep the same configured current management gate on claims and effects."""
    return ExecutionStore(
        factory,
        management_catalog=catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    ), EffectStore(
        factory,
        management_catalog=catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
        receipt_events=NativeReceiptEventPublisher(catalog),
    )
