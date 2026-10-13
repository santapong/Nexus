"""Isolated company profile startup/liveness with no legacy services or intake."""

import pytest
from litestar.exceptions import ServiceUnavailableException
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings


def services() -> CompanyServices:
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(expire_on_commit=False)
    return CompanyServices(
        directory=PersistentCompanyDirectory(factory),
        journal=CompanyJournal(factory),
        controls=CompanyControls(factory),
    )


@pytest.mark.parametrize("secret", ["", "secret", "nexus-dev-secret-change-in-production"])
def test_weak_auth_configuration_denies_company_profile_startup(
    monkeypatch: pytest.MonkeyPatch,
    secret: str,
) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", secret)
    with pytest.raises(ServiceUnavailableException):
        create_company_app(services())


def test_unapproved_jwt_algorithm_denies_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", "unit-fixture-key-with-at-least-32-characters")
    monkeypatch.setattr(settings, "jwt_algorithm", "HS384")
    with pytest.raises(ServiceUnavailableException):
        create_company_app(services())


async def test_liveness_is_explicitly_intake_disabled_without_database_or_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", "unit-fixture-key-with-at-least-32-characters")
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    async with AsyncTestClient(create_company_app(services())) as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"
        assert response.json()["intake_enabled"] is False
        missing = await client.post("/api/v2/company/work", json={"title": "unauthorized intake"})
        assert missing.status_code == 404
        protected = await client.get("/api/v2/company")
        assert protected.status_code == 401
        malformed = await client.post(
            "/api/v2/companies/00000000-0000-0000-0000-000000000001/pause",
            json={"paused": "false"},
        )
        assert malformed.status_code == 401
