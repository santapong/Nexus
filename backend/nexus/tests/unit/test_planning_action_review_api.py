"""Actual router/JWT and protected-file review; native SQL delivery remains supplied."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api import company_management_read_routes as routes
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.control_store import CompanyControls
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management import action_review_store as review_module
from nexus.company.management.action_review_contracts import ActionReview
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.owner_view_sources import SourceDisclosure
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.unit.test_company_auth import TEST_KEY
from nexus.tests.unit.test_planning_action_review import STATIC_RESOURCE, review_case
from nexus.tests.unit.test_planning_prepared_store import Fixture


async def routed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Fixture, Litestar, DirectoryMembership]:
    f, reviews = await review_case(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    directory = PersistentCompanyDirectory(f.store.factory)
    company = DirectoryCompany(
        company_id=f.scope.company_id,
        workspace_id=f.owner.workspace_id,
        owner_id=f.owner.principal_id,
        company_active=True,
        workspace_active=True,
    )
    member = DirectoryMembership(
        company_id=f.scope.company_id,
        principal_id=f.owner.principal_id,
        role="owner",
        principal_active=True,
        membership_active=True,
    )

    @asynccontextmanager
    async def session(*args: object, **kwargs: object) -> AsyncIterator[AsyncSession]:
        yield f.session

    monkeypatch.setattr(directory, "_session", session)
    row = MagicMock()
    row.one_or_none.return_value = (company, member)
    cast(MagicMock, f.session).execute = AsyncMock(return_value=row)
    common = CompanyServices(
        directory, CompanyJournal(f.store.factory), CompanyControls(f.store.factory)
    )
    management = ManagementApiServices(
        directory,
        ManagementControlStore(f.store.factory),
        GoalStore(
            f.store.factory,
            PersistentBrainRetriever(
                f.store.factory, f.store.sources.artifacts.blobs, limits=RetrievalLimits()
            ),
        ),
        ManagementPlanStore(f.store.factory, reviews.catalog),
        action_reviews=reviews,
    )
    return f, create_company_app(common, management_services=management), member


def headers(f: Fixture, *, seconds: int = 300) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(f.owner.principal_id),
            "workspace_id": str(f.owner.workspace_id),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=seconds)).timestamp()),
        },
        TEST_KEY,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


def path(f: Fixture) -> str:
    base = f"/api/v2/companies/{f.scope.company_id}/management"
    return base + f"/actions/{f.prepared.request.action_id}/review"


async def test_signed_owner_review_schema_bytes_no_store_and_member_denial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, app, member = await routed(tmp_path, monkeypatch)
    async with AsyncTestClient(app, raise_server_exceptions=True) as client:
        assert (await client.get(path(f))).status_code == 401
        result = await client.get(path(f), headers=headers(f))
        assert result.status_code == 200
        value = ActionReview.model_validate_json(result.content)
        assert value.availability == "available" and value.detail is not None
        assert result.json() == value.model_dump(mode="json", by_alias=True)
        assert result.headers["content-type"].startswith("application/json")
        assert result.headers["cache-control"] == "no-store"
        assert f.prepared.request.input_text not in result.text and str(tmp_path) not in result.text
        schema = (await client.get("/schema/openapi.json")).json()["components"]["schemas"]
        assert {"audit", "availability", "detail"} <= set(schema["ActionReview"]["required"])
        member.role = "member"
        assert (await client.get(path(f), headers=headers(f))).status_code == 403


async def test_original_bearer_expiry_during_actual_private_read_has_no_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, app, _ = await routed(tmp_path, monkeypatch)
    original = f.store.blobs.read
    first = True

    async def blocked(ref: ArtifactRevisionRef) -> bytes:
        nonlocal first
        if first:
            first = False
            await asyncio.sleep(2.2)
        return await original(ref)

    monkeypatch.setattr(f.store.blobs, "read", blocked)
    async with AsyncTestClient(app, raise_server_exceptions=True) as client:
        result = await client.get(path(f), headers=headers(f, seconds=2))
        assert result.status_code == 503
        assert (
            "detail" not in result.json()
            or result.json()["detail"] == "Action review expired; refresh"
        )
        assert f.prepared.request.input_text not in result.text
        until = asyncio.get_running_loop().time() + 4
        while f.store.pending_owners() and asyncio.get_running_loop().time() < until:
            await asyncio.sleep(0.02)
        assert not f.store.pending_owners()


async def test_complete_serialization_cannot_outlive_original_read_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, app, _ = await routed(tmp_path, monkeypatch)
    original = ActionReview.model_dump_json
    now = [clock_us()]

    def serialize(value: ActionReview, *, by_alias: bool | None = None) -> str:
        raw = original(value, by_alias=by_alias)
        now[0] += 31_000_000
        return raw

    def current(end_us: int) -> None:
        if now[0] >= end_us:
            raise TimeoutError("original finite route end")

    monkeypatch.setattr(routes, "clock_us", lambda: now[0])
    monkeypatch.setattr(routes, "require_time", current)
    monkeypatch.setattr(ActionReview, "model_dump_json", serialize)
    async with AsyncTestClient(app, raise_server_exceptions=True) as client:
        result = await client.get(path(f), headers=headers(f))
        assert result.status_code == 503
        assert f.prepared.request.input_text not in result.text


async def test_static_resource_refresh_cannot_extend_first_observed_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, reviews = await review_case(tmp_path, monkeypatch, extra_static=True)
    assert STATIC_RESOURCE not in {
        row.resource_id for row in f.prepared.context.manifest.contributors
    }
    first_expiry = datetime.now(UTC) + timedelta(seconds=0.08)
    calls = 0

    async def disclosure(*args: object) -> SourceDisclosure:
        nonlocal calls
        assert STATIC_RESOURCE in cast(tuple[UUID, ...], args[-1])
        calls += 1
        # The later static observation appears renewed; it cannot replace T1.
        return SourceDisclosure(
            first_expiry if calls == 1 else datetime.now(UTC) + timedelta(seconds=5)
        )

    original = f.store.blobs.read
    first = True

    async def slow_file(ref: ArtifactRevisionRef) -> bytes:
        nonlocal first
        if first:
            first = False
            await asyncio.sleep(0.15)
        return await original(ref)

    monkeypatch.setattr(review_module, "review_disclosure", disclosure)
    monkeypatch.setattr(f.store.blobs, "read", slow_file)
    try:
        with pytest.raises(TimeoutError):
            await reviews.read(
                f.scope, f.owner, f.prepared.request.action_id, end_us=clock_us() + 30_000_000
            )
    finally:
        # Retire actual owned I/O; its late bytes never become a review result.
        await asyncio.gather(*f.store.pending_owners(), return_exceptions=True)
    assert calls >= 1 and not f.store.pending_owners()
