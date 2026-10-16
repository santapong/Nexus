"""Actual typed full10 server configuration; synthetic eligibility, no native funded claim."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.company.management.coding_prepared_contracts import repository_selection
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.execution.coding_application_config import CodingApplicationConfig
from nexus.harness.journal_models import CompanyControl

if TYPE_CHECKING:
    from nexus.execution.coding_application import CodingApplication
from nexus.execution.coding_operator import UnavailableCredential
from nexus.tests.unit.test_coding_intent import prepared_case
from nexus.tests.unit.test_nexus_coding_catalog import coding_configuration
from nexus.tests.unit.test_planning_application import TEST_SIGNER, application_settings


def configuration(root: Path) -> CodingApplicationConfig:
    prepared, catalog, _, lease = prepared_case()
    planning = coding_configuration(root / "planning").model_copy(update={"catalog": catalog})
    role = planning.role_policy.model_copy(
        update={"workflow_name": "company.coding.v1", "model_profile": "engineering"}
    )
    return CodingApplicationConfig(
        planning=planning,
        role_policy=role,
        recipe=prepared.input_recipe,
        registry_id=prepared.request.registry_id,
        max_output_tokens=512,
        worker_id=lease.worker_id,
        code_sources=prepared.sources,
        repository_selection=repository_selection(prepared),
        repository_path=root.resolve(),
        prepared_root=root / "coding-prepared",
        prepared_storage_symbol="coding:prepared",
    )


def application(root: Path) -> CodingApplication:
    from nexus.execution.coding_application import compose_coding_application

    return compose_coding_application(
        async_sessionmaker[AsyncSession](),
        configuration(root),
        application_settings(),
        UnavailableCredential(),
        UnavailableCredential(),
        SecretStr(TEST_SIGNER),
    )


async def routed_application(root: Path, monkeypatch: pytest.MonkeyPatch) -> CodingApplication:
    """Real graph/directory methods with explicit directory SQL-row delivery only."""
    value = application(root)
    company = DirectoryCompany(
        company_id=value.config.admission.company_id,
        workspace_id=value.config.admission.procedure.binding.workspace_id,
        owner_id=value.config.admission.procedure.binding.actor_id,
        company_active=True,
        workspace_active=True,
    )
    member = DirectoryMembership(
        company_id=company.company_id,
        principal_id=company.owner_id,
        role="owner",
        principal_active=True,
        membership_active=True,
    )
    result = MagicMock()
    result.one_or_none.return_value = (company, member)
    delivered = AsyncMock(spec=AsyncSession)
    delivered.execute.return_value = result
    control = CompanyControl(
        company_id=company.company_id,
        owner_id=company.owner_id,
        policy_version=value.config.planning.policy_version,
        price_version=value.config.catalog.models.pricebook_version,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(5),
        paused=False,
    )
    delivered.get.side_effect = lambda model, key: control if model is CompanyControl else None

    @asynccontextmanager
    async def session(*args: object, **kwargs: object) -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, delivered)

    monkeypatch.setattr(value.api.directory, "_session", session)
    return value


async def owner_witness(value: CodingApplication) -> AuthenticatedWorkerIdentity:
    now = datetime.now(UTC)
    bound = value.config.admission.procedure.binding
    token = jwt.encode(
        {
            "sub": str(bound.actor_id),
            "workspace_id": str(bound.workspace_id),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        TEST_SIGNER,
        algorithm="HS256",
    )

    class Credentials:
        async def credential(self) -> SecretStr:
            return SecretStr(token)

    return await NotificationWorkerIdentities(
        Credentials(), SecretStr(TEST_SIGNER), enabled=True
    ).current()


def owner_scope(value: CodingApplication) -> CompanyControlScope:
    return CompanyControlScope(
        company_id=value.config.catalog.company_id,
        principal_id=value.config.admission.procedure.binding.actor_id,
        operation_id=UUID(int=9901),
        trace_id=UUID(int=9902),
    )
