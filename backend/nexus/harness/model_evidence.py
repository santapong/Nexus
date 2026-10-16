"""Protected server-owned immutable provider result envelopes; no caller receipt authority."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, Field

from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.canonical import canonical_sha256
from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    CompanyModelResult,
    request_hash,
)
from nexus.core.llm.company_eligibility import ModelEligibilityProvenance
from nexus.core.llm.company_pricing import ModelContract
from nexus.core.llm.company_registry import ModelRegistration
from nexus.harness.model_authorizer_contracts import (
    InputEstimate,
    ModelInputRecipe,
    require_input_estimate,
)


class ModelEvidence(ModelContract):
    """Complete provenance saved before receipt; source event is the committed billing intent."""

    request: CompanyModelRequest
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: ModelRegistration
    registry_revision: str
    price_version: str
    recipe: ModelInputRecipe
    input_estimate: InputEstimate
    result: CompanyModelResult
    source_event_at: AwareDatetime
    checked_at: AwareDatetime
    owner_id: UUID
    eligibility_provenance: ModelEligibilityProvenance | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    def require_binding(self) -> None:
        """Reject corrupted or scope-spliced stored provider provenance."""
        if (
            self.request_hash != request_hash(self.request)
            or self.result.request_id != self.request.request_id
            or self.model.registry_id != self.request.registry_id
            or self.registry_revision != self.request.registry_revision
            or self.price_version != self.request.price_version
            or self.model.price is None
            or self.model.price.version != self.price_version
            or self.input_estimate.request_hash != self.request_hash
            or self.source_event_at > self.checked_at
            or self.result.billing == "not_issued"
        ):
            raise ValueError("Saved model evidence binding is invalid")
        require_input_estimate(self.request, self.input_estimate, self.recipe)
        whole = self.input_estimate.whole_request
        if whole is not None and whole.model_sha256 != canonical_sha256(self.model):
            raise ValueError("Saved whole-input model identity differs from original model")
        if self.eligibility_provenance is not None:
            self.eligibility_provenance.require_binding(
                self.model, self.request.company_id, self.registry_revision
            )


class ModelEvidenceStore(Protocol):
    """Trusted internal storage adapter; it must save/read actual immutable bytes."""

    async def save(self, evidence: ModelEvidence) -> ArtifactRef:
        """Save server-generated envelope; return a reference bound to actual bytes."""
        ...

    async def load(self, reference: ArtifactRef) -> ModelEvidence:
        """Resolve only this protected store's references and validate bytes/hash."""
        ...


@dataclass(frozen=True, slots=True)
class ModelEvidenceRecord:
    """Actual retained wire and semantic data, never current reader/native permission."""

    evidence: ModelEvidence
    wire: bytes


class FileModelEvidenceStore:
    """Explicit local protected root; deployment storage/durability is a separate concern."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or root.resolve() != root:
            raise ValueError("Evidence root must be absolute and contain no symlink")
        self._root = root
        self._owners: list[asyncio.Task[object]] = []

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Actual unfinished filesystem owners; their completion grants no result authority."""
        return tuple(task for task in self._owners if not task.done() or task.cancelled())

    async def _owned[T](self, call: Callable[[], T]) -> T:
        self._owners[:] = self.pending_owners()
        task = asyncio.create_task(asyncio.to_thread(call))
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return await asyncio.shield(task)
        except BaseException as first:
            first.__dict__["_nexus_model_pending"] = self.pending_owners()
            raise

    def _path(self, company: UUID, action: UUID, request: UUID) -> Path:
        path = self._root / str(company) / str(action) / f"{request}.json"
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError("Protected model evidence path contains a symlink")
        return path

    async def save(self, evidence: ModelEvidence) -> ArtifactRef:
        """Create immutable mode-0400 file; an idempotent retry uses the original record."""
        evidence = ModelEvidence.model_validate_json(evidence.model_dump_json(by_alias=True))
        evidence.require_binding()
        path = self._path(
            evidence.request.company_id, evidence.request.action_id, evidence.request.request_id
        )

        def write() -> ModelEvidence:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            payload = evidence.model_dump_json(by_alias=True).encode()
            temporary = path.with_name(f".{uuid4()}.pending")
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                existing = self._read(path)
                if existing.model_dump(exclude={"checked_at"}) != evidence.model_dump(
                    exclude={"checked_at"}
                ):
                    raise ValueError("Stored model evidence is immutable") from None
                return existing
            finally:
                temporary.unlink()
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return evidence

        saved = await self._owned(write)
        return await self._reference(path, saved)

    @staticmethod
    def _read(path: Path) -> ModelEvidence:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            payload = stream.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError("Model evidence envelope exceeds its bound")
        evidence = ModelEvidence.model_validate_json(payload)
        evidence.require_binding()
        return evidence

    async def _reference(self, path: Path, evidence: ModelEvidence) -> ArtifactRef:
        digest = await self._owned(lambda: hashlib.sha256(path.read_bytes()).hexdigest())
        call = evidence.request
        return ArtifactRef(
            company_id=call.company_id,
            artifact_id=uuid5(call.action_id, str(call.request_id)),
            reference=str(path),
            sha256=digest,
            revision="model-result-envelope-v1",
            allowed_principals=(call.actor_id, evidence.owner_id),
        )

    async def load(self, reference: ArtifactRef) -> ModelEvidence:
        """Caller paths/hashes cannot assert stored evidence or escape the configured root."""
        path = Path(reference.reference)
        if not path.is_relative_to(self._root) or any(
            parent.is_symlink() for parent in (path, *path.parents)
        ):
            raise ValueError("Artifact is outside the protected model evidence store")
        evidence = await self._owned(lambda: self._read(path))
        expected = self._path(
            evidence.request.company_id, evidence.request.action_id, evidence.request.request_id
        )
        if path != expected or reference != await self._reference(path, evidence):
            raise ValueError("Artifact reference does not match actual stored evidence")
        return evidence

    async def load_record(self, reference: ArtifactRef) -> ModelEvidenceRecord:
        """Keep original file bytes; the existing load remains the FIRST read/admission seam."""
        original = self._root
        evidence = await self.load(reference)
        if self._root != original:
            raise ValueError("Original model evidence root changed during load")
        path = self._path(
            evidence.request.company_id, evidence.request.action_id, evidence.request.request_id
        )
        if path != Path(reference.reference):
            raise ValueError("Model record identity differs from actual loaded evidence")
        record = await self._owned(lambda: self._wire_record(original, path, reference, evidence))
        if self._root != original:
            raise ValueError("Original model evidence root changed during wire read")
        return record

    @staticmethod
    def _wire_record(
        root: Path, path: Path, reference: ArtifactRef, evidence: ModelEvidence
    ) -> ModelEvidenceRecord:
        """Bounded descriptor read; final named/FD metadata follows hash and semantic checks.

        Cohesion exception: the original raw hash and unchanged private file/root
        observations must share this actual owned worker and held descriptor.
        """
        directories = (root, path.parent.parent, path.parent)

        def directory_signature() -> tuple[tuple[int, ...], ...]:
            values = []
            for directory in directories:
                row = directory.stat(follow_symlinks=False)
                if (
                    not stat.S_ISDIR(row.st_mode)
                    or stat.S_IMODE(row.st_mode) != 0o700
                    or row.st_uid != os.getuid()
                    or directory.resolve() != directory
                ):
                    raise ValueError("Model evidence directories are not private/owned")
                values.append((row.st_dev, row.st_ino, row.st_mode, row.st_uid))
            return tuple(values)

        def signature(row: os.stat_result) -> tuple[int, ...]:
            if (
                not stat.S_ISREG(row.st_mode)
                or stat.S_IMODE(row.st_mode) != 0o400
                or row.st_uid != os.getuid()
                or row.st_nlink != 1
                or not 0 < row.st_size <= 2_000_000
            ):
                raise ValueError("Model evidence wire file is not bounded/immutable/private")
            return (
                row.st_dev,
                row.st_ino,
                row.st_mode,
                row.st_uid,
                row.st_nlink,
                row.st_size,
                row.st_mtime_ns,
                row.st_ctime_ns,
            )

        roots = directory_signature()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            initial = signature(os.fstat(stream.fileno()))
            raw = stream.read(2_000_001)
            # Bound BEFORE hashing/parsing, without regenerating Python frozenset arrays.
            if not 0 < len(raw) <= 2_000_000 or len(raw) != initial[5]:
                raise ValueError("Model evidence wire exceeds its exact byte bound")
            if hashlib.sha256(raw).hexdigest() != reference.sha256:
                raise ValueError("Original model evidence wire hash differs")
            parsed = ModelEvidence.model_validate_json(raw)
            parsed.require_binding()
            if parsed != evidence:
                raise ValueError("Loaded evidence differs semantically from original model wire")
            if (
                signature(os.fstat(stream.fileno())) != initial
                or signature(path.stat(follow_symlinks=False)) != initial
                or directory_signature() != roots
            ):
                raise ValueError("Model evidence file/root changed during wire read")
            return ModelEvidenceRecord(evidence, raw)
