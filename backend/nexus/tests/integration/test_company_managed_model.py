"""Public native plan plus actual governed SDK wire; all provider I/O is offline mock."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.core.llm.company_adapter_contracts import (
    AuthorizedModelAttempt,
    CompanyModelRequest,
    ServerEndpoint,
)
from nexus.core.llm.company_adapters import CompanyModelAdapters
from nexus.core.llm.company_pricing import CostQuote
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.settings import settings
from nexus.tests.integration.test_company_brain_ingestion import Reader
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_model_authorizer import (
    FixtureEstimator,
    current_registry,
    recipe,
)
from nexus.tests.management_plan_support import configured_plan
from nexus.tests.unit.test_company_provider_conformance import EndpointResolver, request, response


class DiagnosticAuthorizer(PersistentModelCallAuthorizer):
    """Surface a concrete synthetic-fixture positive-path failure instead of a denied wrapper."""

    async def claim(self, call: CompanyModelRequest, quote: CostQuote) -> AuthorizedModelAttempt:
        try:
            return await super().claim(call, quote)
        except ValueError as exc:
            raise AssertionError(str(exc)) from exc


@pytest.fixture
async def managed_model_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_model"
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


@pytest.mark.parametrize("mode", ["configured", "missing", "revoked"])
async def test_managed_gateway_preserves_current_plan_and_m1_one_request_boundary(
    managed_model_factory: async_sessionmaker[AsyncSession], tmp_path: Path, mode: str
) -> None:
    # Keep the full public-service fixture together so no native approval/lease is manufactured.
    factory = managed_model_factory
    plans, payload = await configured_plan(factory, tmp_path / "brain")
    now = datetime.now(UTC)
    registry = current_registry()
    model = registry.models[0]
    assert model.price is not None
    price = model.price.model_copy(
        update={
            "version": "fixture-prices",
            "as_of": now.date(),
            "valid_from": now - timedelta(minutes=1),
            "valid_until": now + timedelta(hours=1),
        }
    )
    model = model.model_copy(
        update={
            "price": price,
            "health": model.health.model_copy(
                update={
                    "checked_at": now - timedelta(minutes=1),
                    "expires_at": now + timedelta(hours=1),
                }
            ),
        }
    )
    registry = registry.model_copy(
        update={
            "revision": "fixture-registry-v1",
            "pricebook_version": "fixture-prices",
            "models": (model,),
        }
    )
    catalog = plans.catalog.model_copy(
        update={"models": registry, "admitted_profiles": frozenset({"engineering"})}
    )
    children = tuple(
        row.model_copy(
            update={"binding": row.binding.model_copy(update={"model_profile": "engineering"})}
        )
        for row in payload.children
    )
    payload = payload.model_copy(
        update={
            "children": children,
            "procedure": payload.procedure.model_copy(
                update={
                    "binding": payload.procedure.binding.model_copy(
                        update={"model_profile": "engineering"}
                    )
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
    plans = ManagementPlanStore(factory, catalog, source_freshness=freshness)
    proposal = await plans.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposal.plan_revision_id,
        proposal.sha256,
        expected_current_revision_id=proposal.plan_revision_id,
    )
    services = ManagementExecutionServices(
        catalog,
        BoundedArtifactReader(
            factory, ProtectedBlobStore(tmp_path / "brain", storage_symbol="fixture.blobs.v1")
        ),
        freshness,
    )
    author = children[0].binding
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
        price_version="fixture-prices",
    )
    action = ActionProposal(
        company_id=COMPANY,
        task_id=author.task_id,
        trace_id=author.trace_id,
        actor_id=author.actor_id,
        action_id=call.action_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{call.registry_id}",
        parameters=model_action_parameters(call, recipe()),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.030000"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(action, scope)
    await journal.approve_registered(
        scope.model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        now,
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope, action.action_id, now, (), identity=identity(author.actor_id)
    )
    lease = await services.execution_store(factory).claim(scope, identity(author.actor_id), uuid4())
    authority_type = DiagnosticAuthorizer if mode == "configured" else PersistentModelCallAuthorizer
    authority = authority_type(
        factory,
        lease,
        identity(author.actor_id),
        registry,
        resources=(),
        input_estimator=FixtureEstimator(),
        input_recipe=recipe(),
        allowed_classification="internal",
        evidence_store=FileModelEvidenceStore(tmp_path / "model"),
        management=services if mode != "missing" else None,
    )
    if mode == "revoked":
        await ManagementControlStore(factory).revoke_mandate(
            control(), identity(OWNER), payload.mandate
        )
    wires: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        return httpx2.Response(200, json=response("openai"))

    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider="openai",
        api_family="openai_responses",
        base_url="https://offline.invalid/v1",
        api_key=SecretStr("offline-fixture-placeholder"),
        transport=httpx2.MockTransport(handle),
        timeout_seconds=1,
    )
    result = await CompanyModelAdapters(
        registry, EndpointResolver(endpoint), authority
    ).request_once(call, now=datetime.now(UTC))
    if mode == "configured":
        assert result.status == "response" and len(wires) == 1
        recorded = await authority.record_result(call, result)
        assert recorded.billing == "known" and recorded.actual_usd is not None
    else:
        assert result.status == "denied" and wires == []
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = await session.get(ExecutionWork, (COMPANY, author.task_id))
        effect = await session.get(EffectIntent, (COMPANY, call.action_id))
        hold = await session.get(CostHold, call.action_id)
        assert work is not None and hold is not None
        assert work.model_requests_used == (1 if mode == "configured" else 0)
        if mode == "configured":
            assert effect is not None and effect.state == "succeeded"
            assert hold.state == "reconciled" and hold.actual_usd == recorded.actual_usd
        else:
            assert effect is None and hold.state == "held" and hold.actual_usd is None
