"""Explicit local UAT assembly starts no provider, model client, queue or worker."""

from dataclasses import dataclass

from litestar import Litestar
from litestar.config.cors import CORSConfig
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
from nexus.company.management.commitment_store import CommitmentStore
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.pilot_authority import PilotReadAuthority
from nexus.company.pilot_catalog import pilot_catalog
from nexus.company.pilot_config import PilotConfig
from nexus.company.pilot_session import PilotSessionService
from nexus.company.pilot_sources import pilot_sources
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal


@dataclass(frozen=True)
class PilotServices:
    base: CompanyServices
    brain: BrainServices
    management: ManagementApiServices
    sessions: PilotSessionService
    reports: OperatingReportStore
    artifacts: BoundedArtifactReader
    freshness: RegisteredSourceFreshness


def compose_pilot(factory: async_sessionmaker[AsyncSession], config: PilotConfig) -> PilotServices:
    directory = PersistentCompanyDirectory(factory)
    blobs = ProtectedBlobStore(config.blob_root, storage_symbol="uat.local-blobs.v1")
    retriever = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    artifacts = BoundedArtifactReader(factory, blobs)
    freshness = RegisteredSourceFreshness(factory, pilot_sources(config))
    catalog = pilot_catalog(config)
    plans = ManagementPlanStore(factory, catalog, source_freshness=freshness)
    reports = OperatingReportStore(factory, catalog, artifacts, freshness)
    sources = OwnerViewSources(artifacts, freshness)
    management = ManagementApiServices(
        directory,
        ManagementControlStore(factory),
        GoalStore(factory, retriever),
        plans,
        views=ManagementOwnerViews(factory, sources),
        commitments=CommitmentStore(factory),
        action_reviews=OwnerActionReviewStore(factory, catalog, sources, reports=reports),
    )
    return PilotServices(
        CompanyServices(directory, CompanyJournal(factory), CompanyControls(factory)),
        BrainServices(
            directory,
            retriever,
            PersistentContextAssembler(
                factory,
                retriever,
                PilotReadAuthority(),
                limits=ContextLimits(policy_version="uat-context-v1"),
            ),
        ),
        management,
        PilotSessionService(directory, config.account_file),
        reports,
        artifacts,
        freshness,
    )


def pilot_app(services: PilotServices) -> Litestar:
    return create_company_app(
        services.base,
        brain_services=services.brain,
        management_services=services.management,
        pilot_sessions=services.sessions,
        cors_config=CORSConfig(
            allow_origins=["http://127.0.0.1:5188", "http://localhost:5188"],
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        ),
    )
