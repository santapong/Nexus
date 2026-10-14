"""Bounded binary export preserves no partial final cache and never buffers the whole store."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from nexus.builder.contracts import BuilderValue, Digest


class StreamedCache(BuilderValue):
    sha256: Digest
    byte_length: int = Field(ge=0, le=2_147_483_648, strict=True)


async def cache_stream(
    reader: asyncio.StreamReader, destination: Path, *, limit: int = 2_147_483_648
) -> StreamedCache:
    if not 0 < limit <= 2_147_483_648:
        raise ValueError("Public cache export bound is invalid")
    temporary = destination.with_name(destination.name + ".pending-" + uuid4().hex)
    descriptor = await asyncio.to_thread(
        os.open, temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as stream:
            while raw := await reader.read(65536):
                size += len(raw)
                if size > limit:
                    raise ValueError("Public cache export exceeds its hard byte bound")
                digest.update(raw)
                await asyncio.to_thread(stream.write, raw)
            await asyncio.to_thread(stream.flush)
            await asyncio.to_thread(os.fsync, stream.fileno())
        await asyncio.to_thread(os.link, temporary, destination, follow_symlinks=False)
        return StreamedCache(sha256=digest.hexdigest(), byte_length=size)
    finally:
        await asyncio.to_thread(temporary.unlink, missing_ok=True)
