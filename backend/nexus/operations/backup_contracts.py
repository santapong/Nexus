"""Typed backup declarations describe bytes, never storage independence or authority."""

import hashlib
from pathlib import PurePosixPath
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from nexus.company.management.base import SHA256, Name, ValueContract


def artifact_path(value: str) -> str:
    """Require one exact relative path; normalization never hides traversal."""
    path = PurePosixPath(value)
    if (
        not value
        or not path.parts
        or len(value) > 512
        or "\\" in value
        or "\x00" in value
        or path.is_absolute()
        or any(part in {".", ".."} for part in path.parts)
        or str(path) != value
    ):
        raise ValueError("Backup artifact path is unavailable")
    return value


class BackupArtifact(ValueContract):
    relative_path: str
    data: bytes
    _path = field_validator("relative_path")(artifact_path)


class BackupFileRecord(ValueContract):
    relative_path: str
    byte_length: int = Field(ge=0, le=268_435_456, strict=True)
    sha256: SHA256
    _path = field_validator("relative_path")(artifact_path)


class BackupManifest(ValueContract):
    schema_version: Literal["nexus.company.backup.v1"] = "nexus.company.backup.v1"
    company_id: UUID
    company_revision: Name
    captured_at: AwareDatetime
    database_bytes: int = Field(gt=0, le=268_435_456, strict=True)
    database_sha256: SHA256
    files: tuple[BackupFileRecord, ...] = Field(max_length=100000)
    storage_independence: Literal["unverified"] = "unverified"
    capture_consistency: Literal["unverified"] = "unverified"


class BackupContents(ValueContract):
    manifest: BackupManifest
    database: bytes
    artifacts: tuple[BackupArtifact, ...]

    @model_validator(mode="after")
    def exact_contents(self) -> Self:
        """Portable bytes alone cannot assert a matching manifest."""
        if (
            len(self.artifacts) > 100000
            or len(self.database) + sum(len(row.data) for row in self.artifacts) > 268_435_456
        ):
            raise ValueError("Backup contents exceed their expanded bound")
        if (
            len(self.database) != self.manifest.database_bytes
            or hashlib.sha256(self.database).hexdigest() != self.manifest.database_sha256
        ):
            raise ValueError("Database bytes differ from backup manifest")
        records = {row.relative_path: row for row in self.manifest.files}
        if len(records) != len(self.manifest.files) or len(
            {row.relative_path for row in self.artifacts}
        ) != len(self.artifacts):
            raise ValueError("Backup artifact names are duplicated")
        if set(records) != {row.relative_path for row in self.artifacts}:
            raise ValueError("Backup artifact names differ from manifest")
        for row in self.artifacts:
            record = records[row.relative_path]
            if (
                len(row.data) != record.byte_length
                or hashlib.sha256(row.data).hexdigest() != record.sha256
            ):
                raise ValueError("Artifact bytes differ from backup manifest")
        return self
