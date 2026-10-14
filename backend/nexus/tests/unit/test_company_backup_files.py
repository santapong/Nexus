"""Restore output is a new private tree; existing paths and links stay untouched."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from nexus.operations.backup_contracts import BackupArtifact, BackupContents
from nexus.operations.backup_files import restore_files
from nexus.operations.backup_package import pack_backup, unpack_backup


def contents() -> BackupContents:
    return unpack_backup(
        pack_backup(
            UUID(int=1),
            "company_015",
            datetime.now(UTC),
            b"dump",
            (BackupArtifact(relative_path="company/source.blob", data=b"source"),),
        )
    )


async def test_new_private_tree_retains_readonly_exact_bytes(tmp_path: Path) -> None:
    target = tmp_path / "restored"
    result = await restore_files(contents(), target)
    assert result.database == target / "database.dump"
    assert result.artifacts == target / "artifacts"
    assert result.database.read_bytes() == b"dump"
    assert (result.artifacts / "company/source.blob").read_bytes() == b"source"
    assert target.stat().st_mode & 0o777 == 0o700
    assert result.database.stat().st_mode & 0o777 == 0o400


async def test_existing_target_denies_without_mutation(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    file = target / "keep"
    file.write_bytes(b"retained")
    with pytest.raises(ValueError):
        await restore_files(contents(), target)
    assert file.read_bytes() == b"retained"


async def test_symlink_target_or_parent_denies(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        await restore_files(contents(), link)
    with pytest.raises(ValueError):
        await restore_files(contents(), link / "new")
    assert not list(outside.iterdir())


async def test_spliced_content_denies_before_target_creation(tmp_path: Path) -> None:
    invalid = contents().model_copy(update={"database": b"changed"})
    target = tmp_path / "restore"
    with pytest.raises(ValueError):
        await restore_files(invalid, target)
    assert not target.exists()
