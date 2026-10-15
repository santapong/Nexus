"""Exact approved synthetic fixture namespace; descriptions never confer native authority."""

import os
from pathlib import Path

from pydantic import Field
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contracts import BuilderCapabilities, RepositoryPin
from nexus.builder.csv_report_contracts import CsvValue
from nexus.builder.engineering_contracts import EngineeringChangeDeclaration
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload

DATABASE = "nexus_company_test_native_csv_engineering_v2"
COMPANY_REVISION = "company_016"
ROOT = Path("/tmp/nexus-csv-native-pg-20261015-2")
PUBLIC = Path("/home/santapong/.codex/nexus-csv-v4-public-fixture-20261014")
PLAN = Path("/home/santapong/.codex/nexus-csv-native-pg-20261015-plan")
# Historical immutable public-input/source lineage, never a new execution source pin.
# A future V2 launch needs its separately frozen current source/operator packet.
SOURCE_HEAD = "930aed362394a6c779870c18fab32a6c9ed802e8"


def require_root(root: Path, *, existing: bool) -> None:
    if root != ROOT or root.resolve() != root or root.is_symlink():
        raise ValueError("CSV native root differs from exact approved namespace")
    if existing:
        info = root.stat()
        if not root.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o700:
            raise ValueError("CSV native root ownership/type/mode differs")
    elif root.exists():
        raise ValueError("CSV native staging requires a new root")


def require_database(url: URL, *, application: bool) -> None:
    if (
        url.drivername != "postgresql+asyncpg"
        or url.database != DATABASE
        or url.username != ("nexus_company_app" if application else "santapong")
        or url.password is not None
        or url.host is not None
        or url.port is not None
        or dict(url.query)
        != {"host": "/tmp/nexus-release-tests-2026-10-13/socket", "port": "55438"}
    ):
        raise ValueError("CSV native database/role/socket differs from exact assigned scope")


class NativeCsvConfig(CsvValue):
    """Exact fixture data only; no credentials, permits, SQL authority or callable payloads."""

    catalog: PlanAdmissionCatalog
    payload: PlanPayload
    declaration: EngineeringChangeDeclaration
    capabilities: BuilderCapabilities
    runtime: NodeRuntimeInputs
    source: RepositoryPin
    source_metadata: ArtifactRevisionRef
    output: ResourceRef
    proof: ResourceRef
    specs: tuple[BuilderExecutionSpec, ...] = Field(min_length=2, max_length=2)
    actions: tuple[ActionProposal, ...] = Field(min_length=2, max_length=2)


async def require_assigned_database(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        assert await session.scalar(text("SELECT current_database()")) == DATABASE
        assert await session.scalar(text("SELECT current_user")) == "nexus_company_app"
        assert (
            await session.scalar(text("SELECT version_num FROM company_alembic_version"))
            == COMPANY_REVISION
        )
        assert (
            await session.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            is False
        )
