"""Actual signed JWT/router/current-owner guard with supplied SQL/native/source delivery."""

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
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.control_store import CompanyControls
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.execution.planning_owner_reads import PlanningApiServices, PlanningInputReview
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.unit.test_company_auth import TEST_KEY
from nexus.tests.unit.test_planning_owner_reads import case
from nexus.tests.unit.test_planning_prepared_store import Fixture


@pytest.fixture(autouse=True)
def signing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")


async def test_optional_mount_has_no_new_default_intake() -> None:
    from nexus.tests.unit.test_company_api import services

    async with AsyncTestClient(create_company_app(services())) as client:
        result = await client.get(
            f"/api/v2/companies/{UUID(int=1)}/planning/actions/{UUID(int=2)}/input"
        )
        assert result.status_code == 404


async def routed_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Fixture, PlanningApiServices, CompanyServices, DirectoryMembership]:
    f, reader = await case(tmp_path, monkeypatch)
    api = PlanningApiServices(reader)
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

    monkeypatch.setattr(api.directory, "_session", session)
    response = MagicMock()
    response.one_or_none.return_value = (company, member)
    cast(MagicMock, f.session).execute = AsyncMock(return_value=response)
    main = CompanyServices(
        api.directory, CompanyJournal(reader.factory), CompanyControls(reader.factory)
    )
    return f, api, main, member


async def test_real_owner_guard_alias_complete_input_and_exact_openapi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, api, main, member = await routed_case(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(f.owner.principal_id),
            "workspace_id": str(f.owner.workspace_id),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "role": "owner",
        },
        TEST_KEY,
        algorithm="HS256",
    )
    headers = {"Authorization": "Bearer " + token}
    path = (
        f"/api/v2/companies/{f.scope.company_id}/planning/actions/"
        f"{f.prepared.request.action_id}/input"
    )
    async with AsyncTestClient(
        create_company_app(main, planning_services=api), raise_server_exceptions=True
    ) as client:
        unauthenticated = await client.get(path)
        assert unauthenticated.status_code == 401
        foreign = await client.get(
            path.replace(str(f.scope.company_id), str(UUID(int=999))), headers=headers
        )
        assert foreign.status_code == 403
        result = await client.get(path, headers=headers)
        assert result.status_code == 200
        value = PlanningInputReview.model_validate_json(result.content)
        assert value.prepared == f.prepared and value.company_completed is False
        assert value.prepared.request.output_schema is not None
        assert "schema_json" in result.json()["prepared"]["request"]["output_schema"]
        assert result.json() == value.model_dump(mode="json", by_alias=True)
        assert result.headers["cache-control"] == "no-store"
        schema = (await client.get("/schema/openapi.json")).json()["components"]["schemas"]
        assert "prepared" in schema["PlanningInputReview"]["required"]
        assert schema["PlanningInputReview"]["properties"]["execution_permitted"]["const"] is False
        assert "schema_json" in schema["JsonSchemaDocument"]["properties"]
        assert "document" not in schema["JsonSchemaDocument"]["properties"]
        member.role = "admin"
        denied = await client.get(path, headers=headers)
        assert denied.status_code == 403
        member.role = "owner"
        f.revoked = True
        assert (await client.get(path, headers=headers)).status_code == 422


async def test_original_request_jwt_expiry_denies_actual_blocked_private_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, api, main, _ = await routed_case(tmp_path, monkeypatch)
    actual = f.store.blobs.read
    first = True

    async def blocked(ref: ArtifactRevisionRef) -> bytes:
        nonlocal first
        if first:
            first = False
            await asyncio.sleep(2.2)
        return await actual(ref)

    monkeypatch.setattr(f.store.blobs, "read", blocked)
    now = datetime.now(UTC)
    expiry = int(now.timestamp()) + 2
    bearer = jwt.encode(
        {
            "sub": str(f.owner.principal_id),
            "workspace_id": str(f.owner.workspace_id),
            "iat": int(now.timestamp()),
            "exp": expiry,
        },
        TEST_KEY,
        algorithm="HS256",
    )
    try:
        async with AsyncTestClient(
            create_company_app(main, planning_services=api), raise_server_exceptions=True
        ) as client:
            assert datetime.now(UTC).timestamp() < expiry
            result = await client.get(
                f"/api/v2/companies/{f.scope.company_id}/planning/actions/{f.prepared.request.action_id}/input",
                headers={"Authorization": "Bearer " + bearer},
            )
            assert result.status_code == 503
            assert "prepared" not in result.json()
            assert f.prepared.request.input_text not in result.text
            owners = f.store.pending_owners()
            assert all(not owner.cancelled() for owner in owners)
            # AsyncTestClient owns a separate server loop. Observe actual settlement
            # before lifespan shutdown; never cancel or await its Tasks on this loop.
            until = asyncio.get_running_loop().time() + 4
            while f.store.pending_owners() and asyncio.get_running_loop().time() < until:
                await asyncio.sleep(0.02)
            assert not f.store.pending_owners()
    finally:
        owners = f.store.pending_owners()
        if owners:
            # Failure path retains conservative ownership instead of claiming settlement.
            assert all(owner.done() for owner in owners)
    assert not f.store.pending_owners()
