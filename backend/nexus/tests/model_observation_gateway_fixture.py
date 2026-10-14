"""Actual approved native Work and SDK mock; synthetic observation is not live qualification."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, ServerEndpoint
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.harness.model_client import GovernedModelClient
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.settings import settings
from nexus.tests.integration.test_company_brain_ingestion import Reader
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_model_authorizer import (
    FixtureEstimator,
    recipe,
)
from nexus.tests.management_plan_support import configured_plan
from nexus.tests.model_observation_registry import observed_registry
from nexus.tests.unit.test_company_provider_conformance import KEY, EndpointResolver, request


@pytest.fixture
async def observed_gateway_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_model_observation_gateway"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class ObservedGateway:
    client: GovernedModelClient
    call: CompanyModelRequest
    registry: ModelRegistry
    observation: ModelEligibilityObservation
    gate: PersistentModelCallAuthorizer
    execution: ExecutionStore
    lease: ExecutionLease
    scope: LedgerScope
    evidence: FileModelEvidenceStore
    management: ManagementExecutionServices


async def managed_observed_plan(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    expires_seconds: int = 3600,
) -> tuple[PlanPayload, ManagementExecutionServices, ModelRegistry, ModelEligibilityObservation]:
    plans, payload = await configured_plan(factory, root)
    registry, observation = observed_registry(expires_seconds)
    catalog = PlanAdmissionCatalog.model_validate(
        plans.catalog.model_dump()
        | {
            "models": registry,
            "model_observations": (observation,),
            "admitted_profiles": frozenset({"engineering"}),
        }
    )
    payload = payload.model_copy(
        update={
            "children": tuple(
                child.model_copy(
                    update={
                        "binding": child.binding.model_copy(
                            update={"model_profile": "engineering"}
                        ),
                    }
                )
                for child in payload.children
            ),
            "procedure": payload.procedure.model_copy(
                update={
                    "binding": payload.procedure.binding.model_copy(
                        update={"model_profile": "engineering"}
                    ),
                }
            ),
        }
    )
    policy = SourcePolicy(
        source_symbol="fixture.source.v1",
        authority_profile="fixture.reported.v1",
        data_classification="internal",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=3600,
        allowed_external_keys=frozenset({"document-1"}),
    )
    freshness = RegisteredSourceFreshness(factory, SourceRegistry((policy,), Reader({})))
    store = ManagementPlanStore(factory, catalog, source_freshness=freshness)
    proposed = await store.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await store.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    management = ManagementExecutionServices(
        catalog,
        BoundedArtifactReader(factory, ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")),
        freshness,
    )
    return payload, management, registry, observation


async def observed_gateway(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    transport: httpx2.AsyncBaseTransport,
    *,
    expires_seconds: int = 3600,
) -> ObservedGateway:
    payload, management, registry, observation = await managed_observed_plan(
        factory,
        root / "brain",
        expires_seconds=expires_seconds,
    )
    author = payload.children[0].binding
    scope = LedgerScope(
        company_id=COMPANY,
        task_id=author.task_id,
        trace_id=author.trace_id,
        principal_id=author.actor_id,
    )
    action_id = uuid4()
    call = request(
        company_id=COMPANY,
        task_id=author.task_id,
        trace_id=author.trace_id,
        actor_id=author.actor_id,
        action_id=action_id,
        attempt_id=action_id,
        request_id=uuid4(),
        registry_revision=registry.revision,
        price_version=registry.pricebook_version,
    )
    proposal = ActionProposal(
        company_id=COMPANY,
        task_id=author.task_id,
        trace_id=author.trace_id,
        actor_id=author.actor_id,
        action_id=action_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{call.registry_id}",
        parameters=model_action_parameters(call, recipe()),
        policy_version="fixture-policy",
        price_version=registry.pricebook_version,
        estimated_cost_usd=Decimal("0.01"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(proposal, scope)
    now = datetime.now(UTC)
    await journal.approve_registered(
        scope.model_copy(update={"principal_id": OWNER}),
        action_id,
        action_hash(proposal),
        now,
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope, action_id, now, (), identity=identity(author.actor_id)
    )
    execution = management.execution_store(factory)
    lease = await execution.claim(scope, identity(author.actor_id), uuid4(), ttl_seconds=60)
    evidence = FileModelEvidenceStore(root / "evidence")
    gate = PersistentModelCallAuthorizer(
        factory,
        lease,
        identity(author.actor_id),
        registry,
        resources=(),
        input_estimator=FixtureEstimator(),
        input_recipe=recipe(),
        allowed_classification="internal",
        evidence_store=evidence,
        management=management,
        model_observations=(observation,),
    )
    endpoint = ServerEndpoint(
        endpoint_id=registry.models[0].endpoint_id,
        provider="openai",
        api_family="openai_responses",
        base_url="https://offline.invalid/v1",
        api_key=SecretStr(KEY),
        transport=transport,
        timeout_seconds=1,
    )
    client = GovernedModelClient(
        registry,
        EndpointResolver(endpoint),
        gate,
        execution,
        lease,
        identity(author.actor_id),
        model_observations=(observation,),
        cleanup_seconds=5,
    )
    return ObservedGateway(
        client, call, registry, observation, gate, execution, lease, scope, evidence, management
    )
