"""Qualified public CAS cache extraction only allows bounded ordinary complete store files."""

from __future__ import annotations

import os
import tarfile
from pathlib import Path

from nexus.builder.paths import relative_path
from nexus.builder.snapshot import parent_descriptor, private_directory


def cache_entries(archive: tarfile.TarFile) -> tuple[tarfile.TarInfo, ...]:
    rows: list[tarfile.TarInfo] = []
    names = set()
    size = 0
    for row in archive:
        name = row.name.rstrip("/") if row.isdir() else row.name
        path = relative_path(name)
        if (
            path.parts[0] != "store"
            or not (row.isfile() or row.isdir())
            or row.sparse
            or name in names
            or len(rows) >= 100000
        ):
            raise ValueError("Public CAS cache archive has unsafe or out-of-bound entries")
        if row.pax_headers or row.uid != 0 or row.gid != 0 or row.mtime != 0 or row.linkname:
            raise ValueError("Public CAS cache archive metadata differs from normalized recipe")
        if row.size < 0:
            raise ValueError("Public CAS cache entry length is invalid")
        size += row.size
        if size > 2_147_483_648:
            raise ValueError("Public CAS cache exceeds its expanded bound")
        names.add(name)
        rows.append(row)
    return tuple(rows)


def extract_cache(archive_path: Path, root: Path) -> None:
    with tarfile.open(archive_path, mode="r:") as archive:
        rows = cache_entries(archive)
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            private_directory(descriptor)
            for row in rows:
                _extract(archive, row, descriptor)
        finally:
            os.close(descriptor)


def _extract(archive: tarfile.TarFile, row: tarfile.TarInfo, root: int) -> None:
    path = relative_path(row.name.rstrip("/") if row.isdir() else row.name)
    parent = parent_descriptor(root, path.parts if row.isdir() else path.parts[:-1])
    try:
        if row.isdir():
            return
        source = archive.extractfile(row)
        if source is None:
            raise ValueError("Public CAS cache entry is unavailable")
        fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o500 if row.mode & 0o111 else 0o400,
            dir_fd=parent,
        )
        with source, os.fdopen(fd, "wb") as target:
            remaining = row.size
            while remaining:
                raw = source.read(min(65536, remaining))
                if not raw:
                    raise ValueError("Public CAS cache entry bytes are incomplete")
                target.write(raw)
                remaining -= len(raw)
    finally:
        os.close(parent)
