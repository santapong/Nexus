"""Protected server-owned immutable provider result envelopes; no caller receipt authority."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, Field

from nexus.company.contracts.knowledge import ArtifactRef
from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    CompanyModelResult,
    request_hash,
)
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


class ModelEvidenceStore(Protocol):
    """Trusted internal storage adapter; it must save/read actual immutable bytes."""

    async def save(self, evidence: ModelEvidence) -> ArtifactRef:
        """Save server-generated envelope; return a reference bound to actual bytes."""
        ...

    async def load(self, reference: ArtifactRef) -> ModelEvidence:
        """Resolve only this protected store's references and validate bytes/hash."""
        ...


class FileModelEvidenceStore:
    """Explicit local protected root; deployment storage/durability is a separate concern."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or root.resolve() != root:
            raise ValueError("Evidence root must be absolute and contain no symlink")
        self._root = root

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

        saved = await asyncio.to_thread(write)
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
        digest = await asyncio.to_thread(lambda: hashlib.sha256(path.read_bytes()).hexdigest())
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
        evidence = await asyncio.to_thread(self._read, path)
        expected = self._path(
            evidence.request.company_id, evidence.request.action_id, evidence.request.request_id
        )
        if path != expected or reference != await self._reference(path, evidence):
            raise ValueError("Artifact reference does not match actual stored evidence")
        return evidence
