"""One fresh immutable L/C owner application; composition grants no actor or model activation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from litestar import Litestar
from litestar.config.cors import CORSConfig
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.api.company_cycle_cost_routes import CycleCostApiServices
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.action_review_store import OwnerActionReviewStore
from nexus.company.management.cycle_coding_sources import CodingCostSources
from nexus.company.management.cycle_cost_snapshot import CycleCostSnapshotReader
from nexus.company.management.cycle_model_reader import CycleModelReader
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.notifications.worker_identity import (
    NotificationWorkerIdentities,
    OpaqueCredentialProvider,
)
from nexus.company_app import create_company_app
from nexus.execution.coding_api_services import CodingApiServices
from nexus.execution.coding_application_config import CodingApplicationConfig
from nexus.execution.coding_lifecycle import CodingLifecycle
from nexus.execution.coding_owner_reads import CodingOwnerReader
from nexus.execution.coding_services import CodingServices
from nexus.execution.planning_application import (
    PlanningApplication,
    compose_planning_application,
    require_planning_http_signer,
)
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.settings import Settings


@dataclass(frozen=True, slots=True)
class CodingApplication:
    config: CodingApplicationConfig
    planning: PlanningApplication
    services: CodingServices
    reads: CodingOwnerReader
    api: CodingApiServices

    @property
    def lifecycle(self) -> CodingLifecycle:
        return self.api.lifecycle

    def require_composition(self) -> None:
        self.planning.require_composition()
        self.services.require_composition()
        self.api.require_composition()
        costs = self.planning.cycle_costs
        if (
            self.api.directory is not self.planning.base.directory
            or self.api.reads is not self.reads
            or self.lifecycle.services is not self.services
            or self.lifecycle.config is not self.config
            or self.services.management is not self.planning.runtime.management
            or self.services.factory is not self.planning.runtime.factory
            or self.services.contexts._retriever is not self.planning.brain.retriever
            or self.services.evidence is not self.planning.runtime.evidence
            or self.services.resolver is not self.planning.runtime.resolver
            or costs is None
            or costs.reads.models.coding is None
            or costs.reads.models.coding.services is not self.services
            or self.planning.management.action_reviews is None
            or self.planning.management.action_reviews.coding is not self.reads
        ):
            raise ValueError("Original shared coding application graph changed")


def compose_coding_application(
    factory: async_sessionmaker[AsyncSession],
    config: CodingApplicationConfig,
    settings: Settings,
    planning_credentials: OpaqueCredentialProvider,
    coding_credentials: OpaqueCredentialProvider,
    signing_key: SecretStr,
) -> CodingApplication:
    """Fresh graph only; optional role providers may deny but never borrow another identity.

    Cohesion exception: build and seal the same actual L/C/cost/review graph
    before exposure; splitting construction would obscure original ownership.
    """
    if (
        settings.jwt_algorithm != "HS256"
        or not settings.jwt_secret_key
        or len(settings.jwt_secret_key) < 32
        or signing_key.get_secret_value() != settings.jwt_secret_key
    ):
        raise ValueError("Coding must use the configured real HTTP signer")
    config = CodingApplicationConfig.model_validate_json(config.model_dump_json(by_alias=True))
    base = compose_planning_application(
        factory, config.planning, settings, planning_credentials, signing_key
    )
    config = config.model_copy(update={"planning": base.config})
    management = base.runtime.management
    contexts = PersistentContextAssembler(
        factory,
        base.brain.retriever,
        ManagementPlanningAuthority(management, config.role_policy, config.recipe),
        limits=ContextLimits(policy_version=config.planning.policy_version),
    )
    services = CodingServices(
        factory=factory,
        management=management,
        contexts=contexts,
        prepared_blobs=ProtectedBlobStore(
            config.prepared_root, storage_symbol=config.prepared_storage_symbol
        ),
        source_views=base.runtime.prepared.sources,
        repository_path=config.repository_path,
        repository_selection=config.repository_selection,
        code_sources=config.code_sources,
        estimator=FullContextInputEstimator(management.catalog.models, config.recipe),
        recipe=config.recipe,
        identities=NotificationWorkerIdentities(coding_credentials, signing_key, enabled=True),
        resolver=base.runtime.resolver,
        evidence=base.runtime.evidence,
        worker_id=config.worker_id,
        registry_id=config.registry_id,
        max_output_tokens=config.max_output_tokens,
    )
    reads = CodingOwnerReader(services)
    lifecycle = CodingLifecycle(config, services, reads)
    old = base.management.action_reviews
    assert old is not None
    reviews = OwnerActionReviewStore(
        factory,
        management.catalog,
        services.source_views,
        reports=base.management.reports,
        planning=base.runtime.prepared,
        coding=reads,
    )
    owner = replace(base.management, action_reviews=reviews)
    directory = base.base.directory
    if type(directory) is not PersistentCompanyDirectory:
        raise ValueError("Coding needs its actual persistent company directory")
    costs = CycleCostApiServices(
        directory,
        CycleCostSnapshotReader(
            factory,
            management.catalog,
            CycleModelReader(
                factory,
                management.catalog,
                services.evidence,
                planning=base.runtime.prepared,
                coding=CodingCostSources(services),
            ),
        ),
    )
    # Replace only the NEW unexposed wrappers. Original L native stores/lifecycle are unchanged.
    base = replace(base, management=owner, cycle_costs=costs)
    value = CodingApplication(
        config, base, services, reads, CodingApiServices(directory, reads, lifecycle)
    )
    value.require_composition()
    return value


def coding_app(value: CodingApplication) -> Litestar:
    """Mount actual owner controls; no account, worker, model or company bootstrap."""
    value.require_composition()
    require_planning_http_signer(value.planning)
    key = value.services.identities._signing_key
    from nexus.settings import settings

    if key is None or settings.jwt_secret_key != key.get_secret_value():
        raise ValueError("Coding HTTP signer differs")
    return create_company_app(
        value.planning.base,
        brain_services=value.planning.brain,
        management_services=value.planning.management,
        planning_services=value.planning.planning,
        cycle_cost_services=value.planning.cycle_costs,
        coding_services=value.api,
        cors_config=CORSConfig(
            allow_origins=["http://127.0.0.1:5188", "http://localhost:5188"],
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        ),
    )
