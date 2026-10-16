"""Concrete shared L/C application composition; no credential/key/SQL startup."""

from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.execution.coding_application import compose_coding_application
from nexus.execution.coding_application_preflight import preflight_coding_database
from nexus.execution.coding_operator import UnavailableCredential
from nexus.execution.qualification_application import preflight_qualification_database
from nexus.settings import settings
from nexus.tests.unit.coding_application_fixture import application, configuration
from nexus.tests.unit.test_planning_application import TEST_SIGNER, application_settings


def test_l_c_and_complete_cost_owner_graph_share_actual_stores(tmp_path: Path) -> None:
    value = application(tmp_path)
    value.require_composition()
    assert value.services.factory is value.planning.runtime.factory
    assert value.services.management is value.planning.runtime.management
    assert value.services.contexts._retriever is value.planning.brain.retriever
    assert value.services.evidence is value.planning.runtime.evidence
    assert value.services.contexts._authority is not value.planning.runtime.contexts._authority
    assert value.planning.cycle_costs is not None
    assert value.planning.cycle_costs.reads.models.coding is not None
    assert value.planning.cycle_costs.reads.models.coding.services is value.services
    assert value.planning.management.action_reviews is not None
    assert value.planning.management.action_reviews.coding is value.reads


def test_wrong_real_signer_denied_before_source_or_credential_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.brain.blob_store import ProtectedBlobStore

    monkeypatch.setattr(
        ProtectedBlobStore, "__init__", lambda *a, **k: pytest.fail("Wrong signer opened storage")
    )
    with pytest.raises(ValueError, match="signer"):
        compose_coding_application(
            async_sessionmaker[AsyncSession](),
            configuration(tmp_path),
            application_settings(),
            UnavailableCredential(),
            UnavailableCredential(),
            SecretStr("wrong"),
        )


@pytest.mark.parametrize("schema", ["company_016", "company_017", "company_018"])
async def test_full_c_boot_requires_exact017_without_actor_key_or_work_lookups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, schema: str
) -> None:
    value = application(tmp_path)
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    sql = AsyncMock(side_effect=[False, schema, "on", "on", "on"])
    monkeypatch.setattr(AsyncSession, "scalar", sql)
    actor = AsyncMock(side_effect=AssertionError("Owner/history boot acquired an actor"))
    key = AsyncMock(side_effect=AssertionError("Owner/history boot acquired provider key"))
    monkeypatch.setattr(type(value.services.identities), "current", actor)
    monkeypatch.setattr(type(value.services.resolver), "resolve", key)
    if schema == "company_017":
        await preflight_coding_database(value, end_us=clock_us() + 5_000_000)
        assert sql.await_count == 5
    else:
        with pytest.raises(ValueError, match="explicit normal company schema"):
            await preflight_coding_database(value, end_us=clock_us() + 5_000_000)
        assert sql.await_count == 2
    actor.assert_not_awaited()
    key.assert_not_awaited()


@pytest.mark.parametrize(
    "versions,schema,allowed",
    [
        (("company_016",), "company_016", True),
        (("company_016",), "company_017", False),
        (("company_016", "company_017"), "company_017", True),
        (("company_016", "company_017"), "company_018", False),
    ],
)
async def test_finite_l_compatibility_preserves_original_qualification_default(
    monkeypatch: pytest.MonkeyPatch,
    versions: tuple[Literal["company_016", "company_017"], ...],
    schema: str,
    allowed: bool,
) -> None:
    sql = AsyncMock(side_effect=[False, schema, "on", "on", "on"])
    monkeypatch.setattr(AsyncSession, "scalar", sql)
    factory = async_sessionmaker[AsyncSession]()
    if allowed:
        await preflight_qualification_database(
            factory, end_us=clock_us() + 5_000_000, schema_versions=versions
        )
    else:
        with pytest.raises(ValueError):
            await preflight_qualification_database(
                factory, end_us=clock_us() + 5_000_000, schema_versions=versions
            )
