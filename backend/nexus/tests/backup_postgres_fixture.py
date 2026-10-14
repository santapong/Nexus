"""Exclusive source/empty target normal native+DBOS fixture; synthetic public facts only."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import URL
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.operations.backup_config import LocalPostgresBackupConfig
from nexus.operations.backup_postgres import PostgresBackupAdapter
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY, migrate
from nexus.tests.native_process_support import migrate_system

BACKUP_PAIRS = {
    "nexus_company_test_backup_source": "nexus_company_test_backup_restore",
    "nexus_company_test_backup_source_2": "nexus_company_test_backup_restore_2",
}
ALLOWED_DATABASES = frozenset((*BACKUP_PAIRS, *BACKUP_PAIRS.values()))


def selected_source() -> str:
    """Select only a new assigned fixture pair through the existing test database setting."""
    value = (
        make_url(settings.company_test_database_url).database
        if settings.company_test_database_url
        else "nexus_company_test_backup_source"
    )
    if not isinstance(value, str) or value not in BACKUP_PAIRS:
        raise ValueError("Backup drill requires an exact assigned source database")
    return value


SOURCE = selected_source()
TARGET = BACKUP_PAIRS[SOURCE]
SOCKET = "/tmp/nexus-release-tests-2026-10-13/socket"


def local_url(database: str, user: str = "santapong") -> URL:
    assert database in ALLOWED_DATABASES
    return URL.create(
        "postgresql+asyncpg",
        username=user,
        database=database,
        query={"host": SOCKET, "port": "55438"},
    )


@dataclass(frozen=True)
class BackupDatabase:
    factory: async_sessionmaker[AsyncSession]
    adapter: PostgresBackupAdapter


@pytest.fixture
async def backup_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[BackupDatabase]:
    monkeypatch.setattr(
        settings,
        "company_test_database_url",
        local_url(SOURCE).render_as_string(hide_password=False),
    )
    config = LocalPostgresBackupConfig(
        enabled=True,
        company_id=COMPANY,
        socket=Path(SOCKET),
        port=55438,
        admin_user="santapong",
        source_database=SOURCE,
        target_database=TARGET,
        restore_root=tmp_path / "restore",
        timeout_seconds=90,
    )
    admin = create_async_engine(local_url(SOURCE))
    app = create_async_engine(local_url(SOURCE, "nexus_company_app"))
    adapter = PostgresBackupAdapter(config)
    try:
        async with adapter.connection(target=True) as target:
            from nexus.operations.backup_postgres import require_empty_target

            await require_empty_target(target)
        async with adapter.connection() as source:
            await require_empty_target(source)
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        await migrate_system()
        yield BackupDatabase(async_sessionmaker(app, expire_on_commit=False), adapter)
    finally:
        await app.dispose()
        await admin.dispose()
