"""Concrete planning composition and real async task retention; no model or DB activation."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx2
import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context import ContextLimits, ContextSelection
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_support import PlanSourceFreshness
from nexus.company.management.planning_authority import (
    ManagementPlanningAuthority,
    PlanningRolePolicy,
)
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.planning_services import (
    APPLICATION,
    QUEUE,
    REGISTRATION,
    VERSION,
    WORKFLOW,
    PlanningServices,
)
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.tests.unit.test_company_input_bounds import supported
from nexus.tests.unit.test_company_input_estimator import recipe
from nexus.tests.unit.test_company_provider_conformance import EndpointResolver


def services(tmp_path: Path) -> PlanningServices:
    """Concrete components, synthetic catalog/JWT only; no DB READ or quality claim."""
    factory = async_sessionmaker[AsyncSession]()
    original = supported()
    registry = ModelRegistry.model_validate(
        original.model_dump()
        | {
            "models": (
                original.models[0].model_dump() | {"allowed_data": frozenset({"confidential"})},
            )
        }
    )
    selected = recipe()
    blobs = ProtectedBlobStore(tmp_path / "brain", storage_symbol="fixture:brain")
    artifacts = BoundedArtifactReader(factory, blobs)
    freshness = cast(PlanSourceFreshness, object())  # No SQL/source delivery in constructors.
    management = ManagementExecutionServices(
        PlanAdmissionCatalog(
            company_id=registry.company_id,
            models=registry,
            admitted_profiles=frozenset({"engineering"}),
            check_recipes=frozenset(),
        ),
        artifacts,
        freshness,
    )
    authority = ManagementPlanningAuthority(
        management,
        PlanningRolePolicy(
            company_id=registry.company_id,
            workflow_name=WORKFLOW,
            workflow_version=VERSION,
            model_profile="engineering",
            data_classification="confidential",
            role_system_text="Fixed server planning role; supplied test configuration",
        ),
        selected,
    )
    contexts = PersistentContextAssembler(
        factory,
        PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits()),
        authority,
        limits=ContextLimits(policy_version="context-v1"),
    )
    key = SecretStr("finite-in-memory-test-signing-key-with-32-bytes")

    class Credentials:
        async def credential(self) -> SecretStr:
            now = datetime.now(UTC)
            return SecretStr(
                jwt.encode(
                    {
                        "sub": str(UUID(int=3)),
                        "workspace_id": str(UUID(int=2)),
                        "iat": int((now - timedelta(seconds=1)).timestamp()),
                        "exp": int((now + timedelta(minutes=5)).timestamp()),
                    },
                    key.get_secret_value(),
                    algorithm="HS256",
                )
            )

    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider="openai",
        api_family="openai_responses",
        base_url="https://offline.invalid/v1",
        api_key=SecretStr("fake-test-provider-key"),
        timeout_seconds=1,
        transport=httpx2.MockTransport(lambda _: httpx2.Response(500)),
    )
    return PlanningServices(
        factory,
        management,
        contexts,
        PlanningPreparedStore(factory, blobs, OwnerViewSources(artifacts, freshness), selected),
        FullContextInputEstimator(registry, selected),
        selected,
        NotificationWorkerIdentities(Credentials(), key, enabled=True),
        EndpointResolver(endpoint),
        FileModelEvidenceStore(tmp_path / "results"),
        UUID(int=99),
        registry.models[0].registry_id,
        256,
        ContextSelection(company_id=registry.company_id),
    )


def test_concrete_same_factory_composition_and_frozen_config(tmp_path: Path) -> None:
    value = services(tmp_path)
    value.require_composition()
    assert value.execution._factory is value.factory
    object.__setattr__(value, "registry_id", "foreign-model")
    with pytest.raises(ValueError, match="composition"):
        value.require_composition()


def test_planning_workflow_is_fixed_server_registration() -> None:
    assert (WORKFLOW, VERSION, QUEUE, APPLICATION) == (
        "company.planning.v1",
        "v1",
        "nexus.planning",
        "nexus-planning",
    )
    assert (
        REGISTRATION.workflow_name,
        REGISTRATION.workflow_version,
        REGISTRATION.queue_name,
        REGISTRATION.application_name,
    ) == (WORKFLOW, VERSION, QUEUE, APPLICATION)


async def test_resource_wait_does_not_cancel_actual_owner() -> None:
    from nexus.execution.planning_services import wait_resources

    entered, finish = asyncio.Event(), asyncio.Event()

    async def actual() -> str:
        entered.set()
        await finish.wait()
        return "actual-resource-return"

    owner = asyncio.create_task(actual())
    await entered.wait()
    waiter = asyncio.create_task(
        wait_resources(
            (cast(asyncio.Future[object], owner),), asyncio.get_running_loop().time() + 1
        )
    )
    waiter.cancel("Original caller stop")
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not owner.done()
    finish.set()
    assert await owner == "actual-resource-return"
