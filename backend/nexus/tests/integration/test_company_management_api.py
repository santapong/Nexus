"""Actual HTTP owner plan approvals use public native stores without dispatch/model intake."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.integration.test_company_api import KEY, headers
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, migrate
from nexus.tests.management_plan_support import configured_plan


@pytest.fixture
async def management_api_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_api"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool),
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


@pytest.mark.parametrize("mount", [False, True])
async def test_opt_in_current_owner_plan_admission_registers_only_exact_bounded_work(
    management_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path, mount: bool
) -> None:
    factory = management_api_factory
    plans, payload = await configured_plan(factory, tmp_path)
    directory = PersistentCompanyDirectory(factory)
    retriever = PersistentBrainRetriever(
        factory,
        ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    )
    management = ManagementApiServices(
        directory, ManagementControlStore(factory), GoalStore(factory, retriever), plans
    )
    app = create_company_app(
        CompanyServices(directory, CompanyJournal(factory), CompanyControls(factory)),
        management_services=management if mount else None,
    )
    base = f"/api/v2/companies/{COMPANY}/management"
    wire_payload = payload.model_dump(mode="json", by_alias=True)
    body = {
        "payload": wire_payload,
        "expected_current_revision_id": None,
    }
    async with AsyncTestClient(app) as client:
        health = await client.get("/health")
        assert health.status_code == 200 and health.json()["intake_enabled"] is False
        proposal = await client.post(base + "/plans", headers=headers(OWNER), json=body)
        assert proposal.status_code == (200 if mount else 404)
        if not mount:
            return
        record = proposal.json()
        revision_id = record["plan_revision_id"]
        assert record["proposed_by"] == str(OWNER)
        decision = {"exact_hash": record["sha256"], "expected_current_revision_id": revision_id}
        stale = await client.post(
            base + f"/plans/{revision_id}/approve",
            headers=headers(OWNER),
            json={**decision, "expected_current_revision_id": str(uuid4())},
        )
        assert stale.status_code == 409
        approved = await client.post(
            base + f"/plans/{revision_id}/approve", headers=headers(OWNER), json=decision
        )
        assert approved.status_code == 200
        replay = await client.post(
            base + f"/plans/{revision_id}/approve", headers=headers(OWNER), json=decision
        )
        assert replay.status_code == 200 and replay.json() == approved.json()
        member = await client.post(base + "/plans", headers=headers(ACTOR), json=body)
        assert member.status_code == 403
        anonymous = await client.post(base + "/plans", json=body)
        assert anonymous.status_code == 401
        foreign = await client.post(
            f"/api/v2/companies/{uuid4()}/management/plans", headers=headers(OWNER), json=body
        )
        assert foreign.status_code == 403
        malformed = {
            **body,
            "payload": {**wire_payload, "plan": {**wire_payload["plan"], "revision": True}},
        }
        assert (
            await client.post(base + "/plans", headers=headers(OWNER), json=malformed)
        ).status_code == 422
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(ExecutionWork)) == 3
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 0
        assert await session.scalar(select(func.count()).select_from(EffectIntent)) == 0


async def test_owner_http_direction_charter_and_goal_preserve_unknown_baseline(
    management_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    import json

    from nexus.company.management.base import RevisionRef
    from nexus.harness.journal_models import CompanyControl
    from nexus.tests.integration.test_company_management_goals import goal
    from nexus.tests.management_control_support import charter, mandate
    from nexus.tests.management_plan_support import VERIFIER

    factory = management_api_factory
    plans, payload = await configured_plan(factory, tmp_path)
    directory = PersistentCompanyDirectory(factory)
    reader = PersistentBrainRetriever(
        factory,
        ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    )
    management = ManagementApiServices(
        directory, ManagementControlStore(factory), GoalStore(factory, reader), plans
    )
    app = create_company_app(
        CompanyServices(directory, CompanyJournal(factory), CompanyControls(factory)),
        management_services=management,
    )
    base = f"/api/v2/companies/{COMPANY}/management"
    async with AsyncTestClient(app) as client:
        mandate_wire = mandate("v2", daily="3").model_dump(mode="json")
        mandate_body = {
            "mandate": mandate_wire,
            "expected_revision_id": str(payload.mandate.revision_id),
        }
        published = await client.post(base + "/mandate", headers=headers(OWNER), json=mandate_body)
        assert published.status_code == 200
        record = published.json()
        reference = RevisionRef.model_validate_json(
            json.dumps({key: record[key] for key in RevisionRef.model_fields})
        )
        charter_body = {
            "charter": charter("v2", verifier=VERIFIER).model_dump(mode="json"),
            "mandate": reference.model_dump(mode="json"),
            "expected_revision_id": str(payload.charters[0].revision_id),
        }
        admitted_charter = await client.post(
            base + "/charters", headers=headers(OWNER), json=charter_body
        )
        assert admitted_charter.status_code == 200 and admitted_charter.json()["version"] == "v2"
        goal_body = {
            "definition": goal(reference).model_dump(mode="json"),
            "version": "v2",
            "expected_revision_id": str(payload.goal.revision_id),
        }
        admitted_goal = await client.post(base + "/goals", headers=headers(OWNER), json=goal_body)
        assert admitted_goal.status_code == 200
        assert admitted_goal.json()["definition"]["metrics"][0]["baseline"]["kind"] == "unknown"
        assert admitted_goal.json()["definition"]["due"]["source_time"]["precision"] == "unknown"
        malformed_money = {
            **mandate_body,
            "mandate": {**mandate_wire, "daily_cap_usd": 2.0},
        }
        assert (
            await client.post(base + "/mandate", headers=headers(OWNER), json=malformed_money)
        ).status_code == 422
        assert (
            await client.post(base + "/goals", headers=headers(ACTOR), json=goal_body)
        ).status_code == 403
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        control = await session.get(CompanyControl, COMPANY)
        assert control is not None and control.daily_cap_usd == 3
        assert await session.scalar(select(func.count()).select_from(ExecutionWork)) == 0
        assert await session.scalar(select(func.count()).select_from(EffectIntent)) == 0
