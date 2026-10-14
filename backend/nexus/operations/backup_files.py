"""Write verified restore bytes only into a new private ordinary tree."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

from nexus.company.management.base import ValueContract
from nexus.operations.backup_contracts import BackupContents


class RestoredFiles(ValueContract):
    database: Path
    artifacts: Path


FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _ordinary_write(directory: int, name: str, raw: bytes) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=directory
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
        info = os.fstat(output.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o777 != 0o400:
        raise ValueError("Restore file protection is unavailable")
    os.fsync(directory)


def _artifact_write(directory: int, name: str, raw: bytes) -> None:
    parts = name.split("/")
    opened = os.dup(directory)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=opened)
                os.fsync(opened)
            except FileExistsError:
                pass
            following = os.open(part, FLAGS, dir_fd=opened)
            os.close(opened)
            opened = following
            if os.fstat(opened).st_mode & 0o777 != 0o700:
                raise ValueError("Restore artifact directory protection is unavailable")
        _ordinary_write(opened, parts[-1], raw)
    finally:
        os.close(opened)


def _contents_write(directory: int, contents: BackupContents) -> None:
    os.mkdir("artifacts", mode=0o700, dir_fd=directory)
    artifacts = os.open("artifacts", FLAGS, dir_fd=directory)
    try:
        _ordinary_write(directory, "database.dump", contents.database)
        for row in contents.artifacts:
            _artifact_write(artifacts, row.relative_path, row.data)
    finally:
        os.close(artifacts)
    os.fsync(directory)


def _write_tree(contents: BackupContents, target: Path) -> RestoredFiles:
    if not target.is_absolute() or target.resolve() != target or target.exists():
        raise ValueError("Restore requires a new absolute nonsymlink target")
    if target.parent.resolve() != target.parent:
        raise ValueError("Restore parent is unavailable")
    parent = os.open(target.parent, FLAGS)
    try:
        if os.fstat(parent).st_mode & 0o777 != 0o700 or os.fstat(parent).st_uid != os.getuid():
            raise ValueError("Restore parent must be owned and private")
        os.mkdir(target.name, mode=0o700, dir_fd=parent)
        os.fsync(parent)
        directory = os.open(target.name, FLAGS, dir_fd=parent)
        try:
            opened = os.fstat(directory)
            if opened.st_mode & 0o777 != 0o700 or opened.st_uid != os.getuid():
                raise ValueError("Restore target protection is unavailable")
            _contents_write(directory, contents)
            current = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError("Restore target changed during write")
            visible = os.stat(target, follow_symlinks=False)
            if target.resolve() != target or (visible.st_dev, visible.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise ValueError("Restore target namespace changed during write")
        finally:
            os.close(directory)
    except FileExistsError:
        raise ValueError("Restore target already exists") from None
    except OSError:
        raise ValueError("Restore directory is unavailable") from None
    finally:
        os.close(parent)
    return RestoredFiles(database=target / "database.dump", artifacts=target / "artifacts")


async def restore_files(contents: BackupContents, target: Path) -> RestoredFiles:
    """Validate all bytes before any write; never overwrite or clean an existing target."""
    contents = BackupContents.model_validate(contents.model_dump())
    return await asyncio.to_thread(_write_tree, contents, target)
