"""Protected qualification observations, separate from ordinary model/profile evidence."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self, cast
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from nexus.builder.contained_query import clock_us
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    CompanyModelResult,
    request_hash,
)
from nexus.core.llm.qualification_contracts import QualificationRecipe, qualification_request
from nexus.execution.runtime_contracts import EffectRecord
from nexus.harness.journal_contracts import LedgerScope

MAX_EVIDENCE = 2_000_000


def current(end_us: int) -> None:
    if type(end_us) is not int or not 0 < clock_us() < end_us:
        raise TimeoutError("Qualification original caller end expired")


class QualificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["nexus.company.model-qualification.evidence.v1"] = (
        "nexus.company.model-qualification.evidence.v1"
    )
    recipe: QualificationRecipe
    request: CompanyModelRequest
    request_sha256: str
    intent: EffectRecord
    provider_result: CompanyModelResult
    owner_id: UUID
    checked_at: AwareDatetime
    caller_interrupted_at_capture: bool = False

    @model_validator(mode="after")
    def exact_issued_observation(self) -> Self:
        call = self.request
        expected = qualification_request(
            self.recipe,
            LedgerScope(
                company_id=call.company_id,
                task_id=call.task_id,
                trace_id=call.trace_id,
                principal_id=call.actor_id,
            ),
            action_id=call.action_id,
            request_id=call.request_id,
        )
        if (
            call != expected
            or self.request_sha256 != request_hash(call)
            or self.provider_result.request_id != call.request_id
            or self.provider_result.billing == "not_issued"
            or self.owner_id != call.actor_id
            or (
                self.intent.company_id,
                self.intent.task_id,
                self.intent.trace_id,
                self.intent.action_id,
            )
            != (call.company_id, call.task_id, call.trace_id, call.action_id)
            or self.intent.attempt_kind != "model_requests"
            or self.intent.state != "intent"
            or self.intent.receipt is not None
            or self.intent.created_at > self.checked_at
        ):
            raise ValueError("Qualification evidence differs from its original issued observation")
        return self


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _file(value: os.stat_result, *, links: int = 1) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_IMODE(value.st_mode) != 0o400
        or value.st_uid != os.getuid()
        or value.st_nlink != links
    ):
        raise ValueError("Qualification evidence must be an owned private immutable file")


class FileQualificationEvidenceStore:
    """Finite private files with actual task ownership; no hard thread-cancellation claim."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or root.resolve() != root or root.is_symlink():
            raise ValueError("Qualification evidence requires a canonical private root")
        self._root = root
        self._owners: list[asyncio.Task[object]] = []

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(task for task in self._owners if not task.done() or task.cancelled())

    async def _owned[T](self, call: Callable[[], T], end_us: int) -> T:
        current(end_us)
        if len(self.pending_owners()) >= 16:
            raise ValueError("Qualification pending evidence workers exceed their bound")
        task = asyncio.create_task(asyncio.to_thread(call))
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        try:
            async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
                result = await asyncio.shield(task)
            current(end_us)
            return result
        except BaseException as error:
            error.__dict__["_nexus_qualification_pending"] = self.pending_owners()
            raise

    def _path(self, evidence: QualificationEvidence) -> Path:
        call = evidence.request
        return self._root / str(call.company_id) / str(call.action_id) / f"{call.request_id}.json"

    def _directories(
        self, path: Path, end_us: int, *, create: bool = True
    ) -> tuple[tuple[Path, tuple[int, ...]], ...]:
        seen = []
        for directory in (self._root, path.parent.parent, path.parent):
            current(end_us)
            if create:
                directory.mkdir(mode=0o700, exist_ok=True)
            value = directory.stat(follow_symlinks=False)
            if (
                not stat.S_ISDIR(value.st_mode)
                or stat.S_IMODE(value.st_mode) != 0o700
                or value.st_uid != os.getuid()
                or directory.resolve() != directory
            ):
                raise ValueError("Qualification evidence directory is not private/canonical")
            seen.append((directory, (value.st_dev, value.st_ino, value.st_uid, value.st_mode)))
        return tuple(seen)

    @staticmethod
    def _rebind(roots: tuple[tuple[Path, tuple[int, ...]], ...], end_us: int) -> None:
        for path, expected in roots:
            value = path.stat(follow_symlinks=False)
            if (value.st_dev, value.st_ino, value.st_uid, value.st_mode) != expected:
                raise ValueError("Qualification evidence directory identity changed")
            current(end_us)

    def _write(self, evidence: QualificationEvidence, raw: bytes, end_us: int) -> ArtifactRef:
        path = self._path(evidence)
        roots = self._directories(path, end_us)
        pending = path.with_name(f".{uuid4()}.pending")
        fd = os.open(pending, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        try:
            with os.fdopen(fd, "w+b") as stream:
                _file(os.fstat(stream.fileno()))
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                current(end_us)
                before = _signature(os.fstat(stream.fileno()))
                stream.seek(0)
                observed = stream.read(MAX_EVIDENCE + 1)
                if observed != raw or _signature(os.fstat(stream.fileno())) != before:
                    raise ValueError("Qualification complete staged evidence changed")
                self._rebind(roots, end_us)
                # Exclusive publication, never replace an old complete or partial result.
                os.link(pending, path, follow_symlinks=False)
                os.unlink(pending)
                _file(os.fstat(stream.fileno()))
                stable = _signature(os.fstat(stream.fileno()))
                if _signature(path.stat(follow_symlinks=False)) != stable:
                    raise ValueError("Qualification published evidence changed")
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self._rebind(roots, end_us)
            if _signature(path.stat(follow_symlinks=False)) != stable:
                raise ValueError("Qualification evidence changed during descriptor closure")
            current(end_us)
            return self._reference(path, raw, evidence)
        finally:
            if pending.exists():
                pending.unlink()

    @staticmethod
    def _reference(path: Path, raw: bytes, evidence: QualificationEvidence) -> ArtifactRef:
        call = evidence.request
        return ArtifactRef(
            company_id=call.company_id,
            artifact_id=uuid5(call.action_id, f"qualification:{call.request_id}"),
            reference=str(path),
            sha256=hashlib.sha256(raw).hexdigest(),
            revision="model-qualification-envelope-v1",
            allowed_principals=(evidence.owner_id,),
        )

    async def save(self, evidence: QualificationEvidence, *, end_us: int) -> ArtifactRef:
        current(end_us)
        value = QualificationEvidence.model_validate_json(evidence.model_dump_json(by_alias=True))
        raw = value.model_dump_json(by_alias=True).encode()
        if not 0 < len(raw) <= MAX_EVIDENCE:
            raise ValueError("Qualification evidence exceeds the complete byte bound")
        current(end_us)
        return await self._owned(lambda: self._write(value, raw, end_us), end_us)

    def _read(self, reference: ArtifactRef, end_us: int) -> QualificationEvidence:
        path = Path(reference.reference)
        if (
            not path.is_relative_to(self._root)
            or path.resolve() != path
            or len(path.relative_to(self._root).parts) != 3
            or path.relative_to(self._root).parts[0] != str(reference.company_id)
        ):
            raise ValueError("Qualification evidence reference escapes its exact store")
        roots = self._directories(path, end_us, create=False)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            _file(os.fstat(stream.fileno()))
            before = _signature(os.fstat(stream.fileno()))
            raw = stream.read(MAX_EVIDENCE + 1)
            value = QualificationEvidence.model_validate_json(raw)
            if (
                len(raw) > MAX_EVIDENCE
                or path != self._path(value)
                or reference != self._reference(path, raw, value)
                or _signature(os.fstat(stream.fileno())) != before
                or _signature(path.stat(follow_symlinks=False)) != before
            ):
                raise ValueError("Qualification evidence bytes/identity/binding changed")
        self._rebind(roots, end_us)
        if _signature(path.stat(follow_symlinks=False)) != before:
            raise ValueError("Qualification evidence changed while closing read descriptor")
        current(end_us)
        return value

    async def load(self, reference: ArtifactRef, *, end_us: int) -> QualificationEvidence:
        return await self._owned(lambda: self._read(reference, end_us), end_us)
