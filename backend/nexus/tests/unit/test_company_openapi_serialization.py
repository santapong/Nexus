"""Actual JSON schema response must describe exact Pydantic money and tuple wire shapes."""

from collections.abc import Callable
from importlib import import_module
from typing import cast

import pytest
from litestar.testing import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.api_services import BrainServices
from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings


def test_runtime_schema_matches_serialized_owner_arrays_and_money(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    monkeypatch.setattr(
        settings, "jwt_secret_key", "unit-only-schema-key-with-at-least-thirty-two-characters"
    )
    factory = async_sessionmaker[AsyncSession]()
    directory = PersistentCompanyDirectory(factory)
    management = ManagementApiServices(
        directory,
        ManagementControlStore(factory),
        MagicMock(spec=GoalStore),
        MagicMock(spec=ManagementPlanStore),
    )
    app = create_company_app(
        CompanyServices(directory, CompanyJournal(factory), CompanyControls(factory)),
        management_services=management,
        brain_services=MagicMock(spec=BrainServices),
    )
    with TestClient(app) as client:
        reply = client.get("/schema/openapi.json")
        portable_yaml = client.get("/schema/openapi.yaml")
    assert reply.status_code == 200
    assert portable_yaml.status_code == 200
    safe_load = cast(Callable[[str], object], import_module("yaml").safe_load)
    assert safe_load(portable_yaml.text) == reply.json()
    schema = reply.json()["components"]["schemas"]
    assert schema["PlanView"]["properties"]["work"]["items"] == {
        "$ref": "#/components/schemas/WorkView"
    }
    assert schema["CompanyView"]["properties"]["goals"]["items"] == {
        "$ref": "#/components/schemas/GoalView"
    }
    assert {
        value.get("type")
        for value in schema["CompanyBudget"]["properties"]["actual_total_usd"]["anyOf"]
    } == {"string", "null"}
