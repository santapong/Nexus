"""Real JWT/router and private financial files with supplied native SQL/source facts."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.company_cycle_cost_routes import CycleCostApiServices
from nexus.company.access import CompanyControlScope
from nexus.company.control_store import CompanyControls
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management import cycle_cost_snapshot as snapshot_module
from nexus.company.management.cycle_cost_contracts import (
    CycleCostRead,
    CycleCostSnapshot,
    FamilyCostCapture,
)
from nexus.company.management.cycle_cost_snapshot import CycleCostSnapshotReader
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.unit.test_company_auth import TEST_KEY
from nexus.tests.unit.test_cycle_model_reader import supplied_case
from nexus.tests.unit.test_nexus_coding_catalog import coding_case


@pytest.fixture(autouse=True)
def signing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")


async def routed_case(root: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    # The operator provides private storage roots. mkdir(parents=True) only applies
    # its explicit mode to the leaf, so nominate both real ancestors before save.
    profile, _ = coding_case()
    for symbol in ("model", "prepared"):
        (root / symbol).mkdir(mode=0o700)
        (root / symbol / str(profile.company_id)).mkdir(mode=0o700)
    f = await supplied_case(root, monkeypatch)
    reader = CycleCostSnapshotReader(f.reader.factory, f.reader.catalog, f.reader)
    observed = FamilyCostCapture(
        observed_at=datetime.now(UTC),
        owner_id=f.owner.identity.principal_id,
        control_policy="policy",
        control_prices="historical-price",
        control_paused=True,
        profile_bound=True,
        works=(f.selected.directory,),
        selections=(f.selected,),
        orphan_holds=(),
        blockers=(),
    )
    monkeypatch.setattr(reader, "_capture_locked", AsyncMock(return_value=observed))
    monkeypatch.setattr(snapshot_module, "management_owner_transaction", f.transaction)
    directory = PersistentCompanyDirectory(reader.factory)
    api = CycleCostApiServices(directory, reader)
    company = DirectoryCompany(
        company_id=f.scope.company_id,
        workspace_id=f.owner.identity.workspace_id,
        owner_id=f.owner.identity.principal_id,
        company_active=True,
        workspace_active=True,
    )
    member = DirectoryMembership(
        company_id=f.scope.company_id,
        principal_id=f.owner.identity.principal_id,
        role="owner",
        principal_active=True,
        membership_active=True,
    )
    session = MagicMock(spec=AsyncSession)
    result = MagicMock()
    result.one_or_none.return_value = (company, member)
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=f.control)

    @asynccontextmanager
    async def supplied_directory(*args: object, **kwargs: object) -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    monkeypatch.setattr(directory, "_session", supplied_directory)
    common = CompanyServices(
        directory, CompanyJournal(reader.factory), CompanyControls(reader.factory)
    )
    return SimpleNamespace(f=f, api=api, common=common, member=member, reader=reader)


def headers(value: SimpleNamespace, *, seconds: int = 300) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(value.f.owner.identity.principal_id),
            "workspace_id": str(value.f.owner.identity.workspace_id),
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + seconds,
            "role": "owner",
        },
        TEST_KEY,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


def path(value: SimpleNamespace) -> str:
    return f"/api/v2/companies/{value.f.scope.company_id}/management/cycle-costs"


async def test_default_app_does_not_mount_family_financial_reads() -> None:
    from nexus.tests.unit.test_company_api import services

    async with AsyncTestClient(create_company_app(services())) as client:
        result = await client.get(f"/api/v2/companies/{UUID(int=1)}/management/cycle-costs")
    assert result.status_code == 404


async def test_actual_protected_model_cost_is_visible_with_partial_family_and_exact_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await routed_case(tmp_path, monkeypatch)
    async with AsyncTestClient(
        create_company_app(value.common, cycle_cost_services=value.api)
    ) as client:
        result = await client.get(path(value), headers=headers(value))
        assert result.status_code == 200, result.text
        saved = CycleCostSnapshot.model_validate_json(result.content)
        assert saved.totals.known_spent_usd == value.f.selected.hold.actual_usd
        assert saved.charges[0].confirmation == "known", saved.charges[0].blockers
        assert saved.charges[0].model_fact is not None
        assert saved.totals.actual_total_usd is None and not saved.complete_membership
        assert not saved.company_completed and len(saved.expected_task_ids) == 11
        assert result.json() == saved.model_dump(mode="json", by_alias=True)
        assert result.headers["cache-control"] == "no-store"
        schema = (await client.get("/schema/openapi.json")).json()["components"]["schemas"]
        money = schema["FamilyChargeTotals"]["properties"]["known_spent_usd"]
        assert money["type"] == "string"
        assert schema["CycleCostSnapshot"]["properties"]["company_completed"]["const"] is False


@pytest.mark.parametrize("denial", ["anonymous", "foreign", "nonowner", "revoked", "expired"])
async def test_current_signed_owner_is_required_before_financial_private_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    denial: str,
) -> None:
    value = await routed_case(tmp_path, monkeypatch)
    private = AsyncMock(side_effect=AssertionError("private financial read before actual owner"))
    monkeypatch.setattr(value.reader, "read", private)
    route, auth = path(value), headers(value)
    status = 403
    if denial == "anonymous":
        auth, status = {}, 401
    elif denial == "foreign":
        route = route.replace(str(value.f.scope.company_id), str(UUID(int=999)))
    elif denial == "nonowner":
        value.member.role = "admin"
    elif denial == "revoked":
        value.member.membership_active = False
    elif denial == "expired":
        auth, status = headers(value, seconds=-1), 401
    async with AsyncTestClient(
        create_company_app(value.common, cycle_cost_services=value.api)
    ) as client:
        result = await client.get(route, headers=auth)
    assert result.status_code == status
    private.assert_not_awaited()


async def test_shortened_reader_window_survives_final_http_serialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import planning_native_facts as clock_module

    value = await routed_case(tmp_path, monkeypatch)
    original = cast(CycleCostSnapshotReader, value.reader).read
    final_end = 0

    async def saved(
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        *,
        end_us: int,
    ) -> CycleCostRead:
        nonlocal final_end
        record = await original(scope, owner, end_us=end_us)
        final_end = clock_us() + 1_000_000
        return CycleCostRead(record.value, final_end)

    actual_dump = CycleCostSnapshot.model_dump_json

    def serialized(self: CycleCostSnapshot, *, by_alias: bool | None = None) -> str:
        raw = actual_dump(self, by_alias=by_alias)
        if final_end:
            monkeypatch.setattr(clock_module, "clock_us", lambda: final_end + 1)
        return raw

    monkeypatch.setattr(value.reader, "read", saved)
    monkeypatch.setattr(CycleCostSnapshot, "model_dump_json", serialized)
    async with AsyncTestClient(
        create_company_app(value.common, cycle_cost_services=value.api)
    ) as client:
        result = await client.get(path(value), headers=headers(value))
    assert result.status_code == 503
    assert "charges" not in result.json() and "totals" not in result.json()
    assert result.headers["cache-control"] == "no-store"


async def test_original_jwt_expiry_during_financial_read_denies_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await routed_case(tmp_path, monkeypatch)
    original = cast(CycleCostSnapshotReader, value.reader).read

    async def blocked(
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        *,
        end_us: int,
    ) -> CycleCostRead:
        await asyncio.sleep(2.2)
        return await original(scope, owner, end_us=end_us)

    monkeypatch.setattr(value.reader, "read", blocked)
    async with AsyncTestClient(
        create_company_app(value.common, cycle_cost_services=value.api)
    ) as client:
        result = await client.get(path(value), headers=headers(value, seconds=2))
    assert result.status_code == 503
    assert "charges" not in result.json()


async def test_original_concrete_api_graph_cannot_be_substituted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await routed_case(tmp_path, monkeypatch)
    replacement = PersistentCompanyDirectory(value.reader.factory)
    object.__setattr__(value.api, "directory", replacement)
    with pytest.raises(ValueError):
        value.api.require_composition()
    with pytest.raises(ValueError):
        create_company_app(value.common, cycle_cost_services=value.api)
