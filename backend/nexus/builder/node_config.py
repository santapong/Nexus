"""Server-only resolved public inputs are byte/mode checked before a native Node intent."""

from __future__ import annotations

import asyncio
import hashlib
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path

from nexus.builder.cache_archive import cache_entries
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.node_input_files import managed_path, require_input_files
from nexus.builder.paths import bounded_digest, relative_path
from nexus.builder.public_tool_extract import _ordinary_entries


@dataclass(frozen=True)
class NodeRuntimeConfig:
    pins: NodeRuntimeInputs
    pnpm_archive: Path
    tools: Path
    cache_archive: Path
    cache: Path
    manifest: Path

    async def revalidate(self) -> None:
        await asyncio.to_thread(self._checked)

    def _checked(self) -> None:
        for path in (self.pnpm_archive, self.tools, self.cache_archive, self.cache, self.manifest):
            managed_path(path)
        require_input_files(self.pins, self.pnpm_archive, self.cache_archive, self.manifest)
        with tarfile.open(self.pnpm_archive, mode="r:gz") as archive:
            rows = _ordinary_entries(archive)
            _checked_tree(archive, rows, self.tools, False)
        with tarfile.open(self.cache_archive, mode="r:") as archive:
            rows = cache_entries(archive)
            _checked_tree(archive, rows, self.cache.parent, True)


def _checked_tree(
    archive: tarfile.TarFile, rows: tuple[tarfile.TarInfo, ...], root: Path, cache: bool
) -> None:
    expected = set()
    for row in rows:
        name = row.name.rstrip("/") if row.isdir() else row.name
        relative_path(name)
        path = root / name
        info = path.lstat()
        if row.isdir():
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("Native Node input directory became a link")
            continue
        expected.add(name)
        mode = (0o500 if row.mode & 0o111 else 0o400) if cache else 0o600
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != mode
            or info.st_size != row.size
        ):
            raise ValueError("Native Node public file type/mode/size differs")
        source = archive.extractfile(row)
        if source is None:
            raise ValueError("Native Node source archive entry is unavailable")
        digest = hashlib.sha256()
        with source:
            while raw := source.read(65536):
                digest.update(raw)
        actual_digest, actual_size = bounded_digest(root, name, row.size)
        if actual_digest != digest.hexdigest() or actual_size != row.size:
            raise ValueError("Native Node public file bytes changed")
    actual = set()
    for index, path in enumerate(root.rglob("*")):
        if index >= (100000 if cache else 2048):
            raise ValueError("Native Node public tree exceeds qualified entry bounds")
        info = path.lstat()
        if stat.S_ISREG(info.st_mode):
            actual.add(str(path.relative_to(root)))
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("Native Node public tree contains a link or special file")
    if actual != expected:
        raise ValueError("Native Node public tree has missing or unreviewed files")
