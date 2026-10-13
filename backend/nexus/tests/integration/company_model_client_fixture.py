"""Private real-PG and actual SDK fixtures; no live provider or production estimator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, ServerEndpoint
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal_models import CostHold, WorkBudget
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer
from nexus.harness.model_client import GovernedModelClient
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidenceStore
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY, TASK, migrate
from nexus.tests.integration.test_company_model_authorizer import FixtureEstimator, gate, recipe
from nexus.tests.integration.test_company_registered_authorization import identity, scope
from nexus.tests.unit.test_company_provider_conformance import KEY, EndpointResolver


@dataclass(frozen=True)
class ClientComposition:
    registry: ModelRegistry
    resolver: EndpointResolver
    gate: PersistentModelCallAuthorizer
    execution: ExecutionStore
    lease: ExecutionLease

    def build(self, cleanup_seconds: float = 1) -> GovernedModelClient:
        return GovernedModelClient(
            self.registry,
            self.resolver,
            self.gate,
            self.execution,
            self.lease,
            identity(),
            cleanup_seconds=cleanup_seconds,
        )


@pytest.fixture
async def client_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not settings.company_test_database_url:
        pytest.skip("Explicit private model client database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_model_client"
    assert settings.company_test_database_url != settings.database_url
    engine = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    async with engine.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    try:
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await engine.dispose()


async def client(
    factory: async_sessionmaker[AsyncSession],
    artifacts: Path,
    transport: httpx2.AsyncBaseTransport,
    *,
    provider: str = "openai",
    gate_type: type[PersistentModelCallAuthorizer] = PersistentModelCallAuthorizer,
    evidence: ModelEvidenceStore | None = None,
    execution_type: type[ExecutionStore] = ExecutionStore,
    cleanup_seconds: float = 1,
) -> tuple[GovernedModelClient, CompanyModelRequest, ClientComposition]:
    from nexus.tests.integration.test_company_model_authorizer import current_registry

    _, call, registry, _ = await gate(factory, artifacts, registry=current_registry(provider))
    execution = execution_type(factory)
    snapshot = await execution.get(scope(), identity())
    assert snapshot.worker_id and snapshot.expires_at and snapshot.segment_id
    lease = ExecutionLease(
        company_id=COMPANY,
        task_id=TASK,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        workspace_id=snapshot.workspace_id,
        run_id=snapshot.registration.run_id,
        workflow_version=snapshot.registration.workflow_version,
        segment_id=snapshot.segment_id,
        worker_id=snapshot.worker_id,
        fence=snapshot.fence,
        expires_at=snapshot.expires_at,
        mode="execute",
    )
    authority = gate_type(
        factory,
        lease,
        identity(),
        registry,
        resources=(),
        input_estimator=FixtureEstimator(),
        input_recipe=recipe(),
        allowed_classification="internal",
        evidence_store=evidence or FileModelEvidenceStore(artifacts),
    )
    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider=provider,
        api_family="openai_responses" if provider == "openai" else "google_generate_content",
        base_url="https://offline.invalid/v1"
        if provider == "openai"
        else "https://offline.invalid",
        api_key=SecretStr(KEY),
        transport=transport,
        timeout_seconds=1,
    )
    composition = ClientComposition(
        registry, EndpointResolver(endpoint), authority, execution, lease
    )
    return composition.build(cleanup_seconds), call, composition


async def rows(
    factory: async_sessionmaker[AsyncSession], call: CompanyModelRequest
) -> tuple[ExecutionWork, EffectIntent | None, CostHold, WorkBudget]:
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = await session.get(ExecutionWork, (COMPANY, TASK))
        effect = await session.get(EffectIntent, (COMPANY, call.action_id))
        hold = await session.get(CostHold, call.action_id)
        budget = await session.get(WorkBudget, (COMPANY, TASK))
        assert work and hold and budget
        return work, effect, hold, budget
