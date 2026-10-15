"""Closed fake SQL metadata adapter; rejects every artifact/body lookup and unknown statement."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.tests.unit.plan_admission_fixture_data import NOW, AdmissionFixture


class MetadataSession:
    def __init__(self, data: AdmissionFixture) -> None:
        self.data = data
        self.now = NOW
        self.body_reads = 0
        self.statements: list[str] = []
        mock = MagicMock(spec=AsyncSession)
        mock.in_transaction.return_value = True
        mock.get = AsyncMock(side_effect=self.get)
        mock.scalar = AsyncMock(side_effect=self.scalar)
        mock.execute = AsyncMock(
            side_effect=AssertionError("Unexpected execute in metadata fixture")
        )
        mock.scalars = AsyncMock(
            side_effect=AssertionError("Unexpected scalars in metadata fixture")
        )
        self.session = cast(AsyncSession, mock)

    async def get(self, model: object, key: object) -> object | None:
        if model is BrainArtifactRevision:
            self.body_reads += 1
            raise AssertionError("Artifact body must not be read by metadata capture")
        return self.data.objects.get((model, key))

    async def scalar(self, query: object) -> object:
        sql = str(query)
        self.statements.append(sql)
        if "clock_timestamp()" in sql:
            return self.now
        if "rolsuper OR rolbypassrls" in sql:
            return False
        if "min(company_brain_resource_access.expires_at)" in sql:
            assert isinstance(query, Select)
            params = query.compile().params
            values = (
                r.expires_at
                for r in self.data.grants
                if r.expires_at is not None
                and r.resource_id in params["resource_id_1"]
                and r.principal_id in params["principal_id_1"]
            )
            return min(values, default=None)
        if "min(company_brain_source_heads.fresh_until)" in sql:
            assert isinstance(query, Select)
            return (
                self.data.head.fresh_until
                if self.data.source.resource_id in query.compile().params["resource_id_1"]
                else None
            )
        if "FROM company_controls" in sql:
            return self.data.control
        if "FROM company_brain_sources" in sql and isinstance(query, Select):
            return (
                self.data.source
                if self.data.source.resource_id in query.compile().params.values()
                else None
            )
        raise AssertionError("Unexpected SQL in closed metadata fixture")


class Policies:
    def __init__(self, data: AdmissionFixture) -> None:
        self.data = data

    def policy(self, symbol: str) -> SourcePolicy:
        assert symbol == self.data.policy.source_symbol
        return self.data.policy


def qualifier(data: AdmissionFixture) -> RegisteredSourceFreshness:
    return RegisteredSourceFreshness(async_sessionmaker(), Policies(data))
