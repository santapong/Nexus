"""Authenticate all bytes and metadata before an empty configured target/new-root restore."""

import asyncio
import hashlib
from time import monotonic
from typing import TYPE_CHECKING

from sqlalchemy import text

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.operations.backup_artifacts import collect_artifacts, location_path, restored_namespace
from nexus.operations.backup_authority import require_capture_owner
from nexus.operations.backup_capture_contracts import (
    MAX_METADATA_BYTES,
    METADATA_PATH,
    NativeCaptureMetadata,
    RestoredCapture,
)
from nexus.operations.backup_contracts import BackupContents
from nexus.operations.backup_files import restore_files
from nexus.operations.backup_inventory import native_inventory
from nexus.operations.backup_package import unpack_backup
from nexus.operations.backup_postgres import require_empty_target
from nexus.operations.backup_seal import open_backup

if TYPE_CHECKING:
    from nexus.operations.backup_capture import OperatorBackupCoordinator


def capture_metadata(contents: BackupContents) -> NativeCaptureMetadata:
    raw = tuple(row.data for row in contents.artifacts if row.relative_path == METADATA_PATH)
    if len(raw) != 1 or len(raw[0]) > MAX_METADATA_BYTES:
        raise ValueError("Backup authenticated operator metadata is unavailable")
    metadata = NativeCaptureMetadata.model_validate_json(raw[0])
    if metadata.database_sha256 != hashlib.sha256(contents.database).hexdigest():
        raise ValueError("Backup dump differs from authenticated metadata")
    expected = {METADATA_PATH, *(location_path(row) for row in metadata.inventory.artifacts)}
    if expected != {row.relative_path for row in contents.artifacts}:
        raise ValueError("Backup artifact namespaces differ from authenticated metadata")
    return metadata


async def restore_capture(
    coordinator: "OperatorBackupCoordinator",
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    envelope: bytes,
) -> RestoredCapture:
    config = coordinator.adapter.config
    config.require_enabled()
    async with asyncio.timeout(180):
        started = monotonic()
        contents = await asyncio.to_thread(
            unpack_backup,
            await asyncio.to_thread(open_backup, envelope, await coordinator.keys.key()),
        )
        metadata = capture_metadata(contents)
        if (
            scope.company_id != config.company_id
            or metadata.company_id != config.company_id
            or contents.manifest.company_id != config.company_id
            or metadata.source_database != config.source_database
            or metadata.company_revision != config.company_revision
            or contents.manifest.company_revision != config.company_revision
        ):
            raise ValueError("Backup configured company/profile differs")
        await coordinator.require_unchanged(metadata.inventory, scope, identity, metadata.drain)
        async with coordinator.adapter.connection(target=True) as connection:
            await require_empty_target(connection)
        await restore_files(contents, config.restore_root)
        await coordinator.adapter.restore(contents.database)
        await compare_target(coordinator, metadata)
        await require_capture_owner(coordinator.factory, scope, identity, coordinator.adapter)
        return RestoredCapture(
            target_database=config.target_database,
            metadata=metadata,
            elapsed_seconds=monotonic() - started,
        )


async def compare_target(
    coordinator: "OperatorBackupCoordinator", metadata: NativeCaptureMetadata
) -> None:
    config = coordinator.adapter.config
    async with coordinator.adapter.connection(target=True) as connection, connection.begin():
        await connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        current = await native_inventory(connection, config.company_id)
    if (metadata.inventory.tables, metadata.inventory.artifacts) != (
        current.tables,
        current.artifacts,
    ):
        raise ValueError("Restored native/database inventory differs")
    symbols = {row.storage_symbol for row in current.artifacts}
    readers = {
        symbol: ProtectedBlobStore(
            restored_namespace(config.restore_root, symbol), storage_symbol=symbol
        )
        for symbol in symbols
    }
    await collect_artifacts(current.artifacts, readers, limit=config.max_bytes)
