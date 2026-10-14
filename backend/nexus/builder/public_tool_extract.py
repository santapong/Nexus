"""Unpack only verified ordinary public pnpm tool files; no installation hooks or execution."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import tarfile
from pathlib import Path

from nexus.builder.paths import relative_path
from nexus.builder.snapshot import parent_descriptor, private_directory


def extract_public_tool(raw: bytes, integrity: str, root: Path) -> None:
    if (
        not 0 < len(raw) <= 33_554_432
        or integrity != "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
    ):
        raise ValueError("Public tool tar bytes differ from the exact integrity pin/bound")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        entries = _ordinary_entries(archive)
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            private_directory(descriptor)
            for row in entries:
                _extract(archive, row, descriptor)
        finally:
            os.close(descriptor)


def _ordinary_entries(archive: tarfile.TarFile) -> tuple[tarfile.TarInfo, ...]:
    entries: list[tarfile.TarInfo] = []
    names = set()
    total = 0
    for row in archive:
        name = row.name.rstrip("/") if row.isdir() else row.name
        path = relative_path(name)
        if (
            path.parts[0] != "package"
            or not (row.isfile() or row.isdir())
            or row.sparse
            or name in names
            or len(entries) >= 2048
        ):
            raise ValueError("Public tool archive contains an unsafe/duplicate/out-of-bound entry")
        if row.size < 0:
            raise ValueError("Public tool entry size is invalid")
        total += row.size
        if total > 33_554_432:
            raise ValueError("Public tool expanded bytes exceed their bound")
        names.add(name)
        entries.append(row)
    return tuple(entries)


def _extract(archive: tarfile.TarFile, row: tarfile.TarInfo, root: int) -> None:
    path = relative_path(row.name.rstrip("/") if row.isdir() else row.name)
    parent = parent_descriptor(root, path.parts if row.isdir() else path.parts[:-1])
    try:
        if row.isdir():
            return
        source = archive.extractfile(row)
        if source is None:
            raise ValueError("Public tool entry bytes are unavailable")
        fd = os.open(
            path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        with source, os.fdopen(fd, "wb") as target:
            raw = source.read(row.size + 1)
            if len(raw) != row.size:
                raise ValueError("Public tool entry bytes differ")
            target.write(raw)
    finally:
        os.close(parent)
