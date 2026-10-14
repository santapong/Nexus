"""Exact bounded ordinary ZIP payload inside the authenticated backup envelope."""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from datetime import datetime
from uuid import UUID

from nexus.operations.backup_contracts import (
    BackupArtifact,
    BackupContents,
    BackupFileRecord,
    BackupManifest,
    artifact_path,
)

MAX_BACKUP_BYTES, MAX_BACKUP_FILES, MAX_MANIFEST_BYTES = 268_435_456, 100000, 16_777_216


def _ordinary_info(name: str) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = (stat.S_IFREG | 0o400) << 16
    entry.compress_type = zipfile.ZIP_DEFLATED
    return entry


def pack_backup(
    company_id: UUID,
    revision: str,
    captured_at: datetime,
    database: bytes,
    artifacts: tuple[BackupArtifact, ...],
) -> bytes:
    """Describe exact byte contents; capture/owner/quiescence are separately qualified."""
    if (
        type(database) is not bytes
        or not database
        or len(artifacts) > MAX_BACKUP_FILES
        or len({row.relative_path for row in artifacts}) != len(artifacts)
        or len(database) + sum(len(row.data) for row in artifacts) > MAX_BACKUP_BYTES
    ):
        raise ValueError("Backup contents exceed their bound")
    files = tuple(
        BackupFileRecord(
            relative_path=artifact_path(row.relative_path),
            byte_length=len(row.data),
            sha256=hashlib.sha256(row.data).hexdigest(),
        )
        for row in sorted(artifacts, key=lambda value: value.relative_path)
    )
    manifest = (
        BackupManifest(
            company_id=company_id,
            company_revision=revision,
            captured_at=captured_at,
            database_bytes=len(database),
            database_sha256=hashlib.sha256(database).hexdigest(),
            files=files,
        )
        .model_dump_json()
        .encode()
    )
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise ValueError("Backup manifest exceeds its bound")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_ordinary_info("manifest.json"), manifest)
        archive.writestr(_ordinary_info("database.dump"), database)
        for row in sorted(artifacts, key=lambda value: value.relative_path):
            archive.writestr(_ordinary_info("artifacts/" + row.relative_path), row.data)
    raw = output.getvalue()
    if len(raw) > MAX_BACKUP_BYTES:
        raise ValueError("Packed backup exceeds its bound")
    return raw


def _entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if (
        len(entries) > MAX_BACKUP_FILES + 2
        or len({row.filename for row in entries}) != len(entries)
        or sum(row.file_size for row in entries) > MAX_BACKUP_BYTES + MAX_MANIFEST_BYTES
        or any(
            row.is_dir() or stat.S_IFMT(row.external_attr >> 16) != stat.S_IFREG for row in entries
        )
        or any(row.flag_bits & 1 for row in entries)
    ):
        raise ValueError("Backup archive metadata is unavailable")
    return {row.filename: row for row in entries}


def _content(archive: zipfile.ZipFile) -> BackupContents:
    entries = _entries(archive)
    if "manifest.json" not in entries or entries["manifest.json"].file_size > MAX_MANIFEST_BYTES:
        raise ValueError("Backup manifest is unavailable")
    manifest = BackupManifest.model_validate_json(archive.read("manifest.json"))
    names = {
        "manifest.json",
        "database.dump",
        *("artifacts/" + row.relative_path for row in manifest.files),
    }
    if set(entries) != names or len({row.relative_path for row in manifest.files}) != len(
        manifest.files
    ):
        raise ValueError("Backup names differ from manifest")
    if manifest.database_bytes + sum(row.byte_length for row in manifest.files) > MAX_BACKUP_BYTES:
        raise ValueError("Backup expanded contents exceed their bound")
    database = _matched(archive, "database.dump", manifest.database_bytes, manifest.database_sha256)
    artifacts = tuple(
        BackupArtifact(
            relative_path=row.relative_path,
            data=_matched(archive, "artifacts/" + row.relative_path, row.byte_length, row.sha256),
        )
        for row in manifest.files
    )
    return BackupContents(manifest=manifest, database=database, artifacts=artifacts)


def _matched(archive: zipfile.ZipFile, name: str, size: int, digest: str) -> bytes:
    if archive.getinfo(name).file_size != size:
        raise ValueError("Backup length differs from manifest")
    with archive.open(name) as source:
        raw = source.read(size + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Backup content differs from manifest")
    return raw


def unpack_backup(raw: bytes) -> BackupContents:
    """Validate every member before returning any restore contents; do not extract."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BACKUP_BYTES:
        raise ValueError("Backup archive exceeds its bound")
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            return _content(archive)
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        raise ValueError("Backup archive is unavailable") from None
