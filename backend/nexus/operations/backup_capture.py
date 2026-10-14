"""Operator-only same-snapshot native+DBOS dump and registered immutable artifact capture."""

import asyncio
import hashlib
from collections.abc import Mapping
from time import monotonic

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.blob_store import BlobReader
from nexus.company.management.canonical import canonical_sha256
from nexus.operations.backup_artifacts import collect_artifacts
from nexus.operations.backup_authority import require_capture_owner
from nexus.operations.backup_capture_contracts import (
    METADATA_PATH,
    NativeCaptureMetadata,
    RestoredCapture,
    SealedCapture,
    metadata_bytes,
)
from nexus.operations.backup_contracts import BackupArtifact
from nexus.operations.backup_drain import BackupKeyProvider, WorkerDrainProvider, WorkerDrainWitness
from nexus.operations.backup_inventory import BackupInventory, native_inventory
from nexus.operations.backup_package import pack_backup
from nexus.operations.backup_postgres import PostgresBackupAdapter, require_source
from nexus.operations.backup_seal import seal_backup


class OperatorBackupCoordinator:
    def __init__(
        self,
        adapter: PostgresBackupAdapter,
        factory: async_sessionmaker[AsyncSession],
        readers: Mapping[str, BlobReader],
        drain: WorkerDrainProvider,
        keys: BackupKeyProvider,
    ) -> None:
        self.adapter, self.factory = adapter, factory
        self.readers, self.drain, self.keys = dict(readers), drain, keys

    async def restore(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, envelope: bytes
    ) -> RestoredCapture:
        from nexus.operations.backup_restore import restore_capture

        return await restore_capture(self, scope, identity, envelope)

    async def capture(
        self, scope: CompanyControlScope, identity: VerifiedIdentity
    ) -> SealedCapture:
        config = self.adapter.config
        config.require_enabled()
        if scope.company_id != config.company_id:
            raise ValueError("Backup operator company differs")
        async with asyncio.timeout(180):
            started = monotonic()
            drain = await self.drain.observe(scope.company_id)
            if (
                drain.source_database != config.source_database
                or drain.company_id != config.company_id
            ):
                raise ValueError("Backup drain source differs")
            await require_capture_owner(self.factory, scope, identity, self.adapter)
            inventory, database, artifacts = await self.snapshot_bytes()
            metadata = NativeCaptureMetadata(
                company_id=config.company_id,
                company_revision=config.company_revision,
                source_database=config.source_database,
                database_sha256=hashlib.sha256(database).hexdigest(),
                inventory=inventory,
                drain=drain,
                operation_id=scope.operation_id,
                audit_trace_id=scope.trace_id,
            )
            artifacts += (
                BackupArtifact(relative_path=METADATA_PATH, data=metadata_bytes(metadata)),
            )
            packed = await asyncio.to_thread(
                pack_backup,
                config.company_id,
                config.company_revision,
                inventory.observed_at,
                database,
                artifacts,
            )
            envelope = await asyncio.to_thread(seal_backup, packed, await self.keys.key())
            await self.require_unchanged(inventory, scope, identity, drain)
            return SealedCapture(
                envelope=envelope,
                metadata_sha256=canonical_sha256(metadata),
                captured_at=inventory.observed_at,
                elapsed_seconds=monotonic() - started,
            )

    async def snapshot_bytes(self) -> tuple[BackupInventory, bytes, tuple[BackupArtifact, ...]]:
        config = self.adapter.config
        async with self.adapter.connection() as connection, connection.begin():
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            await require_source(connection, config)
            inventory = await native_inventory(connection, config.company_id)
            token = await connection.scalar(text("SELECT pg_export_snapshot()"))
            assert isinstance(token, str)
            database = await self.adapter.dump(token)
            artifacts = await collect_artifacts(
                inventory.artifacts, self.readers, limit=config.max_bytes - len(database)
            )
            return inventory, database, artifacts

    async def require_unchanged(
        self,
        original: BackupInventory,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        original_drain: WorkerDrainWitness,
    ) -> None:
        config = self.adapter.config
        async with self.adapter.connection() as connection, connection.begin():
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            await require_source(connection, config)
            current = await native_inventory(connection, config.company_id)
        if (original.tables, original.artifacts) != (current.tables, current.artifacts):
            raise ValueError("Backup source changed during capture")
        current_drain = await self.drain.observe(scope.company_id)
        if (
            (current_drain.company_id, current_drain.source_database, current_drain.workers)
            != (original_drain.company_id, original_drain.source_database, original_drain.workers)
            or current_drain.company_id != config.company_id
            or current_drain.source_database != config.source_database
        ):
            raise ValueError("Backup registered drain inventory changed")
        await require_capture_owner(self.factory, scope, identity, self.adapter)
