"""Authenticated package content is fully matched before a restore writes any files."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from nexus.operations.backup_contracts import BackupArtifact
from nexus.operations.backup_package import pack_backup, unpack_backup


def test_database_and_artifact_bytes_survive_exact_package() -> None:
    artifacts = {"company/artifact/source.blob": b"exact source bytes", "models/result.json": b"{}"}
    packed = pack_backup(
        UUID(int=1),
        "company_015",
        datetime.now(UTC),
        b"PGDMP dump",
        tuple(BackupArtifact(relative_path=name, data=value) for name, value in artifacts.items()),
    )
    restored = unpack_backup(packed)
    assert restored.database == b"PGDMP dump"
    assert {row.relative_path: row.data for row in restored.artifacts} == artifacts
    assert restored.manifest.company_id == UUID(int=1)
    assert restored.manifest.company_revision == "company_015"
    assert restored.manifest.storage_independence == "unverified"


@pytest.mark.parametrize(
    "name", ["../source", "/source", "a/../b", "a\\b", "a//b", "a/./b", "", "a/"]
)
def test_unsafe_or_noncanonical_artifact_paths_denied(name: str) -> None:
    with pytest.raises(ValueError):
        pack_backup(
            UUID(int=1),
            "company_015",
            datetime.now(UTC),
            b"dump",
            (BackupArtifact(relative_path=name, data=b"source"),),
        )


def test_bounded_total_expansion_and_file_count(monkeypatch: pytest.MonkeyPatch) -> None:
    import nexus.operations.backup_package as codec

    monkeypatch.setattr(codec, "MAX_BACKUP_BYTES", 4)
    with pytest.raises(ValueError):
        pack_backup(
            UUID(int=1),
            "company_015",
            datetime.now(UTC),
            b"123",
            (BackupArtifact(relative_path="a", data=b"12"),),
        )
    monkeypatch.setattr(codec, "MAX_BACKUP_BYTES", 10000)
    monkeypatch.setattr(codec, "MAX_BACKUP_FILES", 1)
    with pytest.raises(ValueError):
        pack_backup(
            UUID(int=1),
            "company_015",
            datetime.now(UTC),
            b"dump",
            (
                BackupArtifact(relative_path="a", data=b"1"),
                BackupArtifact(relative_path="b", data=b"2"),
            ),
        )


def test_corrupted_inner_package_never_returns_partial_data() -> None:
    with pytest.raises(ValueError):
        unpack_backup(b"not an archive")
