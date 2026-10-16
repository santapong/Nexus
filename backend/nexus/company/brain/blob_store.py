"""Protected exact company/artifact/revision bytes, written before committed references."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from nexus.company.brain.sources import ArtifactRevisionRef


class BlobConflictError(ValueError):
    """One immutable artifact revision cannot be replaced by another byte sequence."""


class BlobReader(Protocol):
    """Read protected bytes between initial and final current ACL checks."""

    async def read(self, artifact: ArtifactRevisionRef) -> bytes: ...


class BrainBlobStore(BlobReader, Protocol):
    """Configured protected storage; no user path/URL or company-independent hash lookup."""

    @property
    def storage_symbol(self) -> str: ...

    async def save(self, artifact: ArtifactRevisionRef, raw: bytes) -> None: ...


def validate_utf8(raw: bytes, *, max_bytes: int = 2_097_152) -> str:
    """Unsupported bytes reject before refs/head changes, never normalize into another source."""
    if type(raw) is not bytes or not 1 <= len(raw) <= max_bytes:
        raise ValueError("Brain source byte bound is invalid")
    text = raw.decode("utf-8", errors="strict")
    if "\x00" in text:
        raise ValueError("Brain source contains unsupported NUL")
    return text


def _require_bytes(artifact: ArtifactRevisionRef, raw: bytes) -> None:
    validate_utf8(raw)
    if len(raw) != artifact.byte_length or hashlib.sha256(raw).hexdigest() != artifact.sha256:
        raise ValueError("Brain artifact bytes differ from protected hash/length")


class ProtectedBlobStore:
    """Immutable mode0400 files; deployment filesystem/backup qualification remains separate."""

    def __init__(self, root: Path, *, storage_symbol: str) -> None:
        if not root.is_absolute() or root.resolve() != root or root.is_symlink():
            raise ValueError("Blob store requires a protected absolute nonsymlink root")
        self._root, self._symbol = root, storage_symbol
        self._owners: list[asyncio.Task[object]] = []

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(task for task in self._owners if not task.done() or task.cancelled())

    async def _owned[T](self, call: Callable[[], T]) -> T:
        self._owners[:] = list(self.pending_owners())
        task = asyncio.create_task(asyncio.to_thread(call))
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        try:
            return await asyncio.shield(task)
        except BaseException as first:
            first.__dict__["_nexus_blob_pending"] = self.pending_owners()
            raise

    @property
    def storage_symbol(self) -> str:
        return self._symbol

    def _path(self, artifact: ArtifactRevisionRef) -> Path:
        path = (
            self._root
            / str(artifact.company_id)
            / str(artifact.artifact_id)
            / f"{artifact.artifact_revision_id}.blob"
        )
        if any(value.is_symlink() for value in (path, *path.parents)):
            raise ValueError("Blob path contains a symlink")
        return path

    async def save(self, artifact: ArtifactRevisionRef, raw: bytes) -> None:
        _require_bytes(artifact, raw)

        def write() -> None:
            path = self._path(artifact)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            pending = path.with_name(f".{uuid4()}.pending")
            descriptor = os.open(
                pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(pending, path)
            except FileExistsError:
                if self._read(path) != raw:
                    raise BlobConflictError("Protected artifact revision bytes conflict") from None
            finally:
                pending.unlink()
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

        await self._owned(write)

    @staticmethod
    def _read(path: Path) -> bytes:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read(2_097_153)

    async def read(self, artifact: ArtifactRevisionRef) -> bytes:
        raw = await self._owned(lambda: self._read(self._path(artifact)))
        _require_bytes(artifact, raw)
        return raw
