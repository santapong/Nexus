"""Concrete configured financial graph and actual shutdown leaves; no SQL or effects."""

import asyncio
from pathlib import Path
from typing import cast

import pytest
from litestar.testing import AsyncTestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.api.company_cycle_cost_routes import CycleCostApiServices
from nexus.company.management.cycle_cost_snapshot import CycleCostSnapshotReader
from nexus.execution.planning_application import (
    PlanningApplication,
    compose_planning_application,
    planning_app,
)
from nexus.execution.planning_application_runtime import drain_planning_application
from nexus.settings import settings
from nexus.tests.unit.planning_application_fixture import configuration
from nexus.tests.unit.test_nexus_coding_catalog import coding_configuration
from nexus.tests.unit.test_planning_application import (
    TEST_SIGNER,
    SuppliedCredential,
    application_settings,
)


def application(root: Path, *, coding: bool = True) -> PlanningApplication:
    return compose_planning_application(
        async_sessionmaker[AsyncSession](),
        coding_configuration(root) if coding else configuration(root),
        application_settings(),
        SuppliedCredential(),
        SecretStr(TEST_SIGNER),
    )


async def test_full_profile_app_uses_original_native_protected_cost_graph_and_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = application(tmp_path)
    costs = value.cycle_costs
    assert type(costs) is CycleCostApiServices
    assert costs.directory is value.base.directory
    assert costs.reads.factory is value.runtime.factory
    assert costs.reads.catalog is value.runtime.management.catalog
    assert costs.reads.models.evidence is value.runtime.evidence
    assert costs.reads.models.planning is value.runtime.prepared
    assert not costs.reads.pending_owners()
    value.require_composition()
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    async with AsyncTestClient(planning_app(value)) as client:
        document = (await client.get("/schema/openapi.json")).json()
    route = "/api/v2/companies/{company_id}/management/cycle-costs"
    assert route in document["paths"]
    assert "CycleCostSnapshot" in document["components"]["schemas"]


async def test_historical_profile_keeps_financial_route_unconfigured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = application(tmp_path, coding=False)
    assert value.cycle_costs is None
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    async with AsyncTestClient(planning_app(value)) as client:
        document = (await client.get("/schema/openapi.json")).json()
    assert "/api/v2/companies/{company_id}/management/cycle-costs" not in document["paths"]


def test_same_factory_replacement_reader_cannot_replace_original_app_graph(tmp_path: Path) -> None:
    value = application(tmp_path)
    original = value.cycle_costs
    assert original is not None
    replacement = CycleCostApiServices(
        original.directory,
        CycleCostSnapshotReader(
            original.reads.factory, original.reads.catalog, original.reads.models
        ),
    )
    object.__setattr__(value, "cycle_costs", replacement)
    with pytest.raises(ValueError):
        value.require_composition()


async def test_actual_financial_leaf_prevents_runtime_drain_until_settlement(
    tmp_path: Path,
) -> None:
    value = application(tmp_path)
    assert value.cycle_costs is not None
    original = value.cycle_costs
    release = asyncio.Event()
    leaf = asyncio.create_task(release.wait())
    value.cycle_costs.reads.models._owners.append(cast(asyncio.Task[object], leaf))
    drain = asyncio.create_task(drain_planning_application(value))
    try:
        await asyncio.sleep(0.02)
        assert not drain.done()
        assert original.reads.pending_owners() == (leaf,)
        object.__setattr__(value, "cycle_costs", None)
        await asyncio.sleep(0.06)
        assert not drain.done(), "Changing a facade cannot retire the original financial resource"
    finally:
        release.set()
        await leaf
        await drain
    assert not original.reads.pending_owners()
