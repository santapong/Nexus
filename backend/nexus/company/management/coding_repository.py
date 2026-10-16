"""Actual committed code acquisition; a nominated archive is data, never READ authority.

The concrete coding producer must check current actor/source access before this
adapter and before private preparation/issuance. GitSnapshotSpec event metadata
is separately verified by the existing registered Brain Git reader at ingestion.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import tarfile
from collections.abc import Coroutine
from pathlib import Path
from typing import Self, cast

from pydantic import Field, model_validator

from nexus.builder.contained_query import clock_us
from nexus.builder.contracts import BuilderArtifact, RepositoryPin
from nexus.builder.snapshot import (
    MAX_ARCHIVE_BYTES,
    archive_members,
    committed_archive,
    source_path,
)
from nexus.company.brain.base import (
    SHA256,
    BrainContract,
    BrainReadScope,
    ValueContract,
    require_company,
)
from nexus.company.brain.git_source import GitSnapshotSpec
from nexus.company.management.canonical import canonical_sha256


class CodingRepositorySelection(BrainContract):
    """Server-nominated complete file set, not a request-supplied repository selector."""

    source: RepositoryPin
    files: tuple[GitSnapshotSpec, ...] = Field(min_length=1, max_length=32)
    allowed_write_paths: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def complete_nomination(self) -> Self:
        require_company(self.company_id, *self.files)
        paths = tuple(row.path for row in self.files)
        if (
            len(set(paths)) != len(paths)
            or len({row.source_id for row in self.files}) != len(self.files)
            or len(set(self.allowed_write_paths)) != len(self.allowed_write_paths)
            or not set(self.allowed_write_paths) <= set(paths)
            or sum(row.byte_length for row in self.files) > 65_536
            or any(row.commit != self.source.commit for row in self.files)
        ):
            raise ValueError("Coding repository nomination is crossed, incomplete or oversized")
        for path in paths:
            source_path(path)
        return self


class CodingRepositoryFile(ValueContract):
    """Exact UTF8 data from an ordinary selected committed archive member."""

    metadata: BuilderArtifact
    text: str = Field(max_length=65_536)

    @model_validator(mode="after")
    def exact_bytes(self) -> Self:
        raw = self.text.encode("utf-8")
        if (len(raw), hashlib.sha256(raw).hexdigest()) != (
            self.metadata.byte_length,
            self.metadata.sha256,
        ):
            raise ValueError("Coding repository file differs from its exact bytes")
        return self


class CodingRepositoryMaterial(BrainContract):
    """Bounded selected data only; callers cannot use this DTO as publication authority."""

    source: RepositoryPin
    selection_sha256: SHA256
    files: tuple[CodingRepositoryFile, ...] = Field(min_length=1, max_length=32)


class CodingRepositoryRead(ValueContract):
    """Internal original read cutoff, never a public monotonic-time field."""

    value: CodingRepositoryMaterial
    read_end_us: int


def _material(raw: bytes, selection: CodingRepositorySelection) -> CodingRepositoryMaterial:
    if (
        not 0 < len(raw) <= MAX_ARCHIVE_BYTES
        or hashlib.sha256(raw).hexdigest() != selection.source.archive_sha256
    ):
        raise ValueError("Coding archive differs from its complete pinned bytes")
    values: list[CodingRepositoryFile] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            members = {row.name: row for row in archive_members(archive) if row.isfile()}
            for spec in selection.files:
                entry = members.get(spec.path)
                if entry is None or entry.size != spec.byte_length:
                    raise ValueError("Coding selected archive file is missing or resized")
                stream = archive.extractfile(entry)
                if stream is None:
                    raise ValueError("Coding selected archive file is unavailable")
                with stream:
                    body = stream.read(spec.byte_length + 1)
                # SHA1 is Git's object format identity, alongside the stronger complete SHA256 pins.
                blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
                if (len(body), hashlib.sha256(body).hexdigest(), blob) != (
                    spec.byte_length,
                    spec.sha256,
                    spec.git_blob,
                ):
                    raise ValueError("Coding selected Git blob/hash/size differs")
                values.append(
                    CodingRepositoryFile(
                        metadata=BuilderArtifact(
                            path=spec.path,
                            sha256=spec.sha256,
                            byte_length=spec.byte_length,
                        ),
                        text=body.decode("utf-8"),
                    )
                )
    except tarfile.TarError as error:
        raise ValueError("Coding archive metadata is unavailable") from error
    return CodingRepositoryMaterial(
        company_id=selection.company_id,
        source=selection.source,
        selection_sha256=canonical_sha256(selection),
        files=tuple(values),
    )


class CodingRepositoryReader:
    """Own the actual committed-archive and bounded materialization leaves across stop."""

    def __init__(self, repository: Path, selection: CodingRepositorySelection) -> None:
        if not repository.is_absolute() or repository.resolve() != repository:
            raise ValueError("Coding repository requires its exact server-nominated path")
        self._repository = repository
        self._selection = CodingRepositorySelection.model_validate_json(selection.model_dump_json())
        self._original = (self._repository, self._selection, canonical_sha256(self._selection))
        self._owners: list[asyncio.Task[object]] = []
        self._stopped = False

    @property
    def selection_sha256(self) -> str:
        """Describe the immutable nomination; this grants no source or effect permission."""
        return canonical_sha256(self._selection)

    def request_stop(self) -> None:
        """Deny new reads and positive adoption while existing actual resources settle."""
        self._stopped = True

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Cancelled wrappers are not proof that actual Git/thread work has settled."""
        return tuple(row for row in self._owners if not row.done() or row.cancelled())

    def _current(self, end_us: int) -> None:
        if self._stopped or (
            self._repository is not self._original[0]
            or self._selection is not self._original[1]
            or canonical_sha256(self._selection) != self._original[2]
        ):
            raise ValueError("Original coding repository reader is stopped or changed")
        if type(end_us) is not int or clock_us() >= end_us:
            raise TimeoutError("Original coding repository read expired")

    async def _owned[T](self, operation: Coroutine[object, object, T], end_us: int) -> T:
        task: asyncio.Task[T] = asyncio.create_task(operation)
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            return await asyncio.shield(task)

    async def read(self, scope: BrainReadScope, *, end_us: int) -> CodingRepositoryRead:
        """Read exact Git data under audit identifiers; scope shape is not current access."""
        self._current(end_us)
        scope = BrainReadScope.model_validate_json(scope.model_dump_json())
        if (
            scope.company_id != self._selection.company_id
            or scope.task_id is None
            or scope.task_trace_id is None
            or scope.actor_id != scope.principal_id
        ):
            raise ValueError("Coding repository audit scope differs from its nomination")
        end_us = min(end_us, clock_us() + 30_000_000)
        try:
            archive = await self._owned(
                committed_archive(self._repository, self._selection.source), end_us
            )
            self._current(end_us)
            material = await self._owned(
                asyncio.to_thread(_material, archive, self._selection), end_us
            )
            self._current(end_us)
            return CodingRepositoryRead(value=material, read_end_us=end_us)
        except BaseException:
            self.request_stop()
            raise
