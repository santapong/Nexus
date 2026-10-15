"""Bounded binary export; owned FS threads reach terminal before exact path/fd cleanup."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, TypeVar, cast
from uuid import uuid4

from pydantic import Field

from nexus.builder.contracts import BuilderValue, Digest

T = TypeVar("T")


class StreamedCache(BuilderValue):
    sha256: Digest
    byte_length: int = Field(ge=0, le=2_147_483_648, strict=True)


class _OwnedExport:
    """One private-directory export retains a single operation; no hard IO-time bound exists."""

    def __init__(self, destination: Path) -> None:
        self.destination = destination
        self.temporary = destination.with_name(destination.name + ".pending-" + uuid4().hex)
        self.descriptor: int | None = None
        self.stream: BinaryIO | None = None
        self.identity: tuple[int, int] | None = None
        self.linked = False
        self.pending: asyncio.Task[object] | None = None

    def open(self) -> None:
        self.descriptor = os.open(
            self.temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        stat = os.fstat(self.descriptor)
        self.identity = stat.st_dev, stat.st_ino

    async def run(self, operation: Callable[[], T]) -> T:
        task = asyncio.create_task(asyncio.to_thread(operation))
        self.pending = cast(asyncio.Task[object], task)  # Strong reference even after cancellation.
        return await asyncio.shield(task)

    def link(self) -> None:
        os.link(self.temporary, self.destination, follow_symlinks=False)
        self.linked = (
            True  # Record the actual commit inside the worker before its result is awaited.
        )

    def cleanup(self, abort: bool) -> None:
        try:
            if self.stream is not None:
                self.stream.close()
            elif self.descriptor is not None:
                os.close(self.descriptor)
                self.descriptor = None
        finally:
            if abort and self.linked:
                self._unlink_own(self.destination)
            self._unlink_own(self.temporary)

    def _unlink_own(self, path: Path) -> None:
        # This assumes the task-owned private directory, not atomic conditional-unlink protection
        # against adversarial same-UID namespace replacement between stat and unlink.
        try:
            stat = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return
        if self.identity == (stat.st_dev, stat.st_ino):
            path.unlink()

    async def finish(self, original: BaseException | None) -> None:
        failure: BaseException | None = None
        cancelled: asyncio.CancelledError | None = None
        if self.pending is not None:
            failure, cancelled = await _terminal(self.pending)
        abort = original is not None or cancelled is not None or failure is not None
        cleanup_error, later = await _terminal(
            asyncio.create_task(asyncio.to_thread(self.cleanup, abort))
        )
        failure, cancelled = failure or cleanup_error, cancelled or later
        if later is not None:
            # Cancellation during normal cleanup also rolls back the completed owned final link.
            cleanup_error, _ = await _terminal(
                asyncio.create_task(asyncio.to_thread(self.cleanup, True))
            )
            failure = failure or cleanup_error
        primary = original or cancelled or failure
        if primary is not None and failure is not None and failure is not primary:
            primary.add_note("Owned cache settlement/cleanup failed: " + type(failure).__name__)
            primary.__dict__["nexus_cache_ownership"] = self
        if original is None and primary is not None:
            raise primary


async def _terminal[T](
    task: asyncio.Task[T],
) -> tuple[BaseException | None, asyncio.CancelledError | None]:
    """Wait the exact owned task despite repeated cancellation; no thread-kill claim."""
    cancelled: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            cancelled = cancelled or error
        except BaseException:
            break  # The exact terminal exception is retrieved below, never discarded.
    try:
        task.result()
    except BaseException as error:
        return error, cancelled
    return None, cancelled


# Keep one export/finally boundary: no cancellation can close a stream while its worker writes.
async def cache_stream(
    reader: asyncio.StreamReader, destination: Path, *, limit: int = 2_147_483_648
) -> StreamedCache:
    if not 0 < limit <= 2_147_483_648:
        raise ValueError("Public cache export bound is invalid")
    owner = _OwnedExport(destination)
    digest, size = hashlib.sha256(), 0
    try:
        await owner.run(owner.open)
        assert owner.descriptor is not None
        stream = owner.stream = os.fdopen(owner.descriptor, "wb")
        owner.descriptor = None  # The stream owns this exact fd from here onward.
        while raw := await reader.read(65536):
            size += len(raw)
            if size > limit:
                raise ValueError("Public cache export exceeds its hard byte bound")
            digest.update(raw)
            await owner.run(lambda: stream.write(raw))
        await owner.run(stream.flush)
        await owner.run(lambda: os.fsync(stream.fileno()))
        await owner.run(stream.close)
        await owner.run(owner.link)
        return StreamedCache(sha256=digest.hexdigest(), byte_length=size)
    finally:
        await owner.finish(sys.exception())
