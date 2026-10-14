"""Ordinary source inventories bind post changes and prove the baseline stayed unchanged."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from nexus.builder.paths import bounded_digest, permitted_path
from nexus.builder.snapshot import (
    MAX_SOURCE_BYTES,
    MAX_SOURCE_FILES,
    private_directory,
    source_path,
)


def inventory(root: Path) -> dict[str, tuple[str, int]]:
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private_directory(descriptor)
    finally:
        os.close(descriptor)
    result: dict[str, tuple[str, int]] = {}
    pending = [root]
    entries = 0
    size = 0
    while pending:
        parent = pending.pop()
        with os.scandir(parent) as children:
            for child in children:
                entries += 1
                if entries > MAX_SOURCE_FILES:
                    raise ValueError("Builder snapshot file count exceeds its bound")
                name = str(Path(child.path).relative_to(root))
                source_path(name)
                info = child.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(child.path))
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    digest, length = bounded_digest(root, name, MAX_SOURCE_BYTES - size)
                    size += length
                    result[name] = (digest, info.st_mode & 0o777)
                else:
                    raise ValueError("Builder snapshot contains a link or special file")
    return result


def inventory_digest(value: dict[str, tuple[str, int]]) -> str:
    digest = hashlib.sha256()
    for name, (content, mode) in sorted(value.items()):
        digest.update(f"{name}\0{content}\0{mode}\n".encode())
    return digest.hexdigest()


def verify_snapshots(
    baseline: Path,
    post: Path,
    before: dict[str, tuple[str, int]],
    allowed: tuple[str, ...],
) -> tuple[str, str]:
    first = inventory(baseline)
    second = inventory(post)
    if first != before:
        raise ValueError("Builder readonly baseline snapshot changed")
    changed = {name for name in first.keys() | second.keys() if first.get(name) != second.get(name)}
    if any(not permitted_path(name, allowed) for name in changed):
        raise ValueError("Builder post snapshot changed outside declared write paths")
    return inventory_digest(first), inventory_digest(second)
