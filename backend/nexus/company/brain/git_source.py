"""Read a server-nominated immutable Git blob; no checkout, fetch or caller path interpretation."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path, PurePosixPath
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.brain.base import SHA256, BrainContract, Name, SourceTime, Symbol
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_registry import SourceSnapshot
from nexus.company.brain.sources import SourceRegistration


class GitSnapshotSpec(BrainContract):
    """Trusted operator mapping; this model is never accepted by a public source request."""

    source_id: UUID
    source_symbol: Symbol
    external_key: Name
    path: Name
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    git_blob: str = Field(pattern=r"^[0-9a-f]{40}$")
    sha256: SHA256
    byte_length: int = Field(ge=1, le=2_097_152, strict=True)
    source_event: SourceTime

    @model_validator(mode="after")
    def selected_path(self) -> Self:
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or ".git" in path.parts
            or "\\" in self.path
            or "\x00" in self.path
            or str(path) != self.path
            or self.source_event.precision != "instant"
        ):
            raise ValueError("Git snapshot needs an exact ordinary nominated path and commit time")
        return self


class CommittedGitSourceReader:
    """The repo path/specs are process-owned; request revision cannot resolve another ref."""

    def __init__(self, repository: Path, specs: tuple[GitSnapshotSpec, ...]) -> None:
        self._repository = repository
        self._specs = {
            (spec.company_id, spec.source_id): GitSnapshotSpec.model_validate_json(
                spec.model_dump_json()
            )
            for spec in specs
        }
        if len(self._specs) != len(specs) or not specs:
            raise ValueError("Git source reader requires distinct explicit nominated sources")

    async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
        spec = self._specs.get((source.company_id, source.source_id))
        if spec is None or (source.source_symbol, source.external_key, revision) != (
            spec.source_symbol,
            spec.external_key,
            spec.commit,
        ):
            raise BrainDeniedError("Nominated Git source is unavailable")
        row = await self._git("ls-tree", "-z", spec.commit, "--", spec.path, limit=2048)
        if row.count(b"\x00") != 1:
            raise BrainDeniedError("Nominated Git source is unavailable")
        header, path = row[:-1].split(b"\t", 1)
        mode, kind, blob = header.split()
        if (
            mode not in {b"100644", b"100755"}
            or kind != b"blob"
            or (blob.decode("ascii"), path.decode("utf8")) != (spec.git_blob, spec.path)
        ):
            raise BrainDeniedError("Nominated Git source binding changed")
        size = await self._git("cat-file", "-s", spec.git_blob, limit=32)
        if size.strip() != str(spec.byte_length).encode():
            raise BrainDeniedError("Nominated Git source size changed")
        stamp = (
            (await self._git("show", "-s", "--format=%cI", spec.commit, limit=64)).decode().strip()
        )
        if stamp != spec.source_event.value:
            raise BrainDeniedError("Nominated Git commit time changed")
        raw = await self._git("cat-file", "blob", spec.git_blob, limit=spec.byte_length)
        if len(raw) != spec.byte_length or hashlib.sha256(raw).hexdigest() != spec.sha256:
            raise BrainDeniedError("Nominated Git source hash changed")
        return SourceSnapshot(
            company_id=spec.company_id,
            source_id=spec.source_id,
            source_symbol=spec.source_symbol,
            external_key=spec.external_key,
            revision=spec.commit,
            raw_bytes=raw,
            source_event=spec.source_event,
        )

    async def _git(self, *arguments: str, limit: int) -> bytes:
        """Bounded argv invocation; replacements/hooks/network and stderr reflection are absent."""
        process = await asyncio.create_subprocess_exec(
            "git",
            "--no-replace-objects",
            "-C",
            str(self._repository),
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            assert process.stdout is not None
            async with asyncio.timeout(10):
                body = await _read_bounded(process.stdout, limit)
                if await process.wait() != 0:
                    raise BrainDeniedError("Nominated Git source is unavailable")
                return body
        finally:
            if process.returncode is None:
                process.kill()
            # Process.wait() can stall with an unread PIPE even after the child
            # exits. Drain our bounded, local Git output before awaiting cleanup.
            await asyncio.wait_for(process.communicate(), timeout=2)


async def _read_bounded(stream: asyncio.StreamReader, limit: int) -> bytes:
    """A stream read may be partial; drain to EOF without exceeding the nominated size."""
    body = bytearray()
    while True:
        part = await stream.read(min(65_536, limit - len(body) + 1))
        if not part:
            return bytes(body)
        body.extend(part)
        if len(body) > limit:
            raise BrainDeniedError("Nominated Git source exceeds its read bound")
