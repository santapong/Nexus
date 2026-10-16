"""Explicit planning application graph; composition creates no company, approval or model call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from litestar import Litestar
from litestar.config.cors import CORSConfig
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.api_services import BrainServices
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.action_review_store import OwnerActionReviewStore
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.company.management.commitment_store import CommitmentStore
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.metric_queries import MetricQueries
from nexus.company.management.metric_store import MetricStore
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.company.notifications.worker_identity import (
    NotificationWorkerIdentities,
    OpaqueCredentialProvider,
)
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.core.llm.company_endpoints import ServerEndpointBinding, SettingsEndpointResolver
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.planning_application_config import (
    PlanningApplicationConfig,
    PlanningSourcePolicies,
)
from nexus.execution.planning_owner_reads import PlanningApiServices, PlanningInputReader
from nexus.execution.planning_services import PlanningServices
from nexus.harness.journal import CompanyJournal
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.settings import Settings

if TYPE_CHECKING:
    from nexus.execution.planning_lifecycle import PlanningLifecycle


@dataclass(frozen=True, slots=True)
class PlanningApplication:
    """One shared native/storage graph, separate from actual startup or execution."""

    config: PlanningApplicationConfig
    base: CompanyServices
    brain: BrainServices
    management: ManagementApiServices
    planning: PlanningApiServices
    runtime: PlanningServices

    @property
    def lifecycle(self) -> PlanningLifecycle:
        """Return the same concrete lifecycle retained by both HTTP service bundles."""
        value = self.planning.lifecycle
        if value is None:
            raise ValueError("Planning application lifecycle is unavailable")
        return value

    def require_composition(self) -> None:
        """Descriptions cannot substitute a different runtime or protected input store."""
        if (
            self.planning.lifecycle is None
            or self.management.planning_lifecycle is not self.planning.lifecycle
            or self.planning.reads.store is not self.runtime.prepared
            or self.runtime.contexts._retriever is not self.brain.retriever
            or self.management.action_reviews is None
            or self.management.action_reviews.planning is not self.runtime.prepared
        ):
            raise ValueError("Original planning application composition changed")
        self.runtime.require_composition()
        self.planning.reads._composition()
        if self.planning.require_lifecycle() is not self.management.require_lifecycle():
            raise ValueError("Original planning lifecycle service hooks changed")
        self.lifecycle.require_composition()


def planning_endpoint_bindings(
    config: PlanningApplicationConfig,
) -> tuple[ServerEndpointBinding, ...]:
    """Only supported official families; no endpoint URL or key comes from a request."""
    values: dict[str, ServerEndpointBinding] = {}
    for row in config.catalog.models.models:
        binding = ServerEndpointBinding(
            row.endpoint_id,
            row.provider,
            row.api_family,
            "https://api.openai.com/v1"
            if row.provider == "openai"
            else "https://generativelanguage.googleapis.com",
        )
        if binding.endpoint_id in values and values[binding.endpoint_id] != binding:
            raise ValueError("Planning endpoint identifier has conflicting official bindings")
        values[binding.endpoint_id] = binding
    return tuple(values.values())


def compose_planning_application(
    factory: async_sessionmaker[AsyncSession],
    config: PlanningApplicationConfig,
    settings: Settings,
    credentials: OpaqueCredentialProvider,
    signing_key: SecretStr,
) -> PlanningApplication:
    """Use the existing HTTP signer and finite actor source; never mint an account/session.

    Cohesion exception: construction keeps the same concrete factory, source,
    context, native and lifecycle objects visibly joined before exposing HTTP.
    """
    from nexus.execution.planning_lifecycle import PlanningLifecycle

    if (
        settings.jwt_algorithm != "HS256"
        or not settings.jwt_secret_key
        or len(settings.jwt_secret_key) < 32
        or signing_key.get_secret_value() != settings.jwt_secret_key
    ):
        raise ValueError("Planning must use the configured HTTP signer")
    config = PlanningApplicationConfig.model_validate_json(config.model_dump_json(by_alias=True))
    bindings = planning_endpoint_bindings(config)
    directory = PersistentCompanyDirectory(factory)
    blobs = ProtectedBlobStore(
        config.storage.brain_root, storage_symbol=config.storage.brain_storage_symbol
    )
    artifacts = BoundedArtifactReader(factory, blobs)
    policies = PlanningSourcePolicies(policies=config.source_policies)
    freshness = RegisteredSourceFreshness(factory, policies)
    retriever = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    management = ManagementExecutionServices(config.catalog, artifacts, freshness)
    contexts = PersistentContextAssembler(
        factory,
        retriever,
        ManagementPlanningAuthority(management, config.role_policy, config.recipe),
        limits=ContextLimits(policy_version=config.policy_version),
    )
    sources = OwnerViewSources(artifacts, freshness)
    prepared = PlanningPreparedStore(
        factory,
        ProtectedBlobStore(
            config.storage.prepared_root, storage_symbol=config.storage.prepared_storage_symbol
        ),
        sources,
        config.recipe,
    )
    runtime = PlanningServices(
        factory,
        management,
        contexts,
        prepared,
        FullContextInputEstimator(config.catalog.models, config.recipe),
        config.recipe,
        NotificationWorkerIdentities(credentials, signing_key, enabled=True),
        SettingsEndpointResolver(settings, bindings),
        FileModelEvidenceStore(config.storage.model_evidence_root),
        config.worker_id,
        config.registry_id,
        config.max_output_tokens,
        config.selection,
    )
    lifecycle = PlanningLifecycle(config, runtime)
    reports = OperatingReportStore(factory, config.catalog, artifacts, freshness)
    owner = ManagementApiServices(
        directory,
        ManagementControlStore(factory),
        GoalStore(factory, retriever),
        ManagementPlanStore(factory, config.catalog, source_freshness=freshness),
        views=ManagementOwnerViews(factory, sources),
        commitments=CommitmentStore(factory),
        action_reviews=OwnerActionReviewStore(
            factory, config.catalog, sources, reports=reports, planning=prepared
        ),
        cancellations=WorkCancellationStore(factory),
        metrics=MetricStore(factory, config.catalog, artifacts, freshness),
        metric_queries=MetricQueries(factory, config.catalog, artifacts, freshness),
        reports=reports,
        planning_lifecycle=lifecycle,
    )
    value = PlanningApplication(
        config,
        CompanyServices(directory, CompanyJournal(factory), CompanyControls(factory)),
        BrainServices(directory, retriever, contexts),
        owner,
        PlanningApiServices(
            PlanningInputReader(prepared, config.catalog.models), lifecycle=lifecycle
        ),
        runtime,
    )
    value.require_composition()
    return value


def require_planning_http_signer(services: PlanningApplication) -> None:
    """HTTP and actual actor verification must retain the existing configured signer."""
    from nexus.settings import settings as http_settings

    # HTTP handlers use this existing signer, while native actors use their
    # original injected verifier. Never mount two different signing authorities.
    key = services.runtime.identities._signing_key
    if (
        http_settings.jwt_algorithm != "HS256"
        or key is None
        or http_settings.jwt_secret_key != key.get_secret_value()
    ):
        raise ValueError("Planning must use the configured HTTP signer")


def planning_app(services: PlanningApplication) -> Litestar:
    """Mount existing company owner/Brain/planning routes; no worker or account bootstrap."""
    require_planning_http_signer(services)
    services.require_composition()
    return create_company_app(
        services.base,
        brain_services=services.brain,
        management_services=services.management,
        planning_services=services.planning,
        cors_config=CORSConfig(
            allow_origins=["http://127.0.0.1:5188", "http://localhost:5188"],
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        ),
    )
