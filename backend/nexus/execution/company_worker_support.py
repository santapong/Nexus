"""Server-owned offline model/artifact registry, resolved inside the effect step."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.actions import ResourceRevision
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.execution.company_worker_contracts import OfflineOutput
from nexus.execution.dbos_contracts import SegmentCommand

WorkerPhase = Literal["intent_committed", "model_called", "output_saved", "receipt_recorded"]
MODEL_PROFILE = "offline-company-v1"
MODEL_REGISTRY_VERSION = "offline-fixtures-v1"


class WorkerHook(Protocol):
    """Trusted server test/observability callback, never serialized in a work command."""

    async def __call__(self, phase: WorkerPhase, command: SegmentCommand) -> None:
        """Observe a committed/issued boundary without granting work authority."""
        ...


@dataclass(frozen=True)
class OfflineWorkerServices:
    """Process-local dependencies; models, factories and paths never enter checkpoints."""

    factory: async_sessionmaker[AsyncSession]
    artifact_root: Path
    worker_id: UUID
    lease_ttl_seconds: int = 60
    hook: WorkerHook | None = None
    resources: tuple[ResourceRevision, ...] = (
        ResourceRevision(resource="fixture:report", revision="offline-v1"),
        ResourceRevision(resource="fixture:source", revision="offline-v1"),
    )

    async def observe(self, phase: WorkerPhase, command: SegmentCommand) -> None:
        """Record a server-owned observation; absence consumes no model request."""
        if self.hook is not None:
            await self.hook(phase, command)


class DraftParameters(BaseModel):
    """Only bounded draft text is accepted; paths, recipients and model overrides are absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    draft: str = Field(min_length=1, max_length=2000)


def offline_agent() -> Agent[None, str]:
    """Register one procedural test model with no hidden tool/validation retry or fallback."""
    return Agent(
        TestModel(
            call_tools=[], custom_output_text="Synthetic Nexus readiness draft; offline test only."
        ),
        output_type=str,
        deps_type=type(None),
        name="nexus_company_offline_draft_v1",
        retries=0,
        tools=[],
    )


async def generate_draft(agent: Agent[None, str], parameters: DraftParameters) -> str:
    """One plain-string TestModel request; no live provider or in-agent tool execution."""
    result = await agent.run(
        parameters.draft, usage_limits=UsageLimits(request_limit=1, tool_calls_limit=0)
    )
    if result.usage.requests != 1 or result.usage.tool_calls != 0:
        raise ValueError("Offline agent exceeded its single registered request")
    return result.output


class OfflineArtifacts:
    """Hash-bound local evidence under a server-owned root, independent of DBOS checkpoints."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, command: SegmentCommand) -> Path:
        if not self.root.is_absolute() or self.root.is_symlink():
            raise ValueError("Offline artifacts require a trusted absolute nonsymlink root")
        path = self.root / str(command.company_id) / str(command.action_id) / "output.json"
        if any(parent.is_symlink() for parent in (path, path.parent, path.parent.parent)):
            raise ValueError("Offline output path contains a symlink")
        return path

    async def load(self, command: SegmentCommand) -> OfflineOutput | None:
        """Read a bounded saved envelope; missing output means the issued outcome is unknown."""

        def read() -> str | None:
            path = self._path(command)
            if not path.exists():
                return None
            if path.stat().st_size > 32_768:
                raise ValueError("Offline envelope exceeds its size limit")
            return path.read_text()

        value = await asyncio.to_thread(read)
        if value is None:
            return None
        wrapper = json.loads(value)
        payload = wrapper["payload"]
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if wrapper["sha256"] != digest:
            raise ValueError("Saved offline envelope content hash disagrees")
        return OfflineOutput.model_validate_json(payload)

    async def save(self, command: SegmentCommand, output: OfflineOutput) -> None:
        """Atomically preserve issued output before receipt/checkpoint; do not replace evidence."""
        payload = output.model_dump_json()
        wrapper = json.dumps(
            {"payload": payload, "sha256": hashlib.sha256(payload.encode()).hexdigest()}
        )

        def write() -> None:
            path = self._path(command)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.read_text() != wrapper:
                    raise ValueError("Offline output is immutable")
                return
            temporary = path.with_suffix(".tmp")
            with temporary.open("x") as stream:
                stream.write(wrapper)
                stream.flush()
            temporary.replace(path)

        await asyncio.to_thread(write)

    async def reference(self, command: SegmentCommand, owner_id: UUID) -> ArtifactRef:
        """Return the address/hash of actual saved bytes, not an invented output artifact."""

        def read() -> tuple[Path, str]:
            path = self._path(command)
            return path, hashlib.sha256(path.read_bytes()).hexdigest()

        path, digest = await asyncio.to_thread(read)
        return ArtifactRef(
            company_id=command.company_id,
            artifact_id=uuid5(command.action_id, "offline-output-v1"),
            reference=str(path),
            sha256=digest,
            revision="offline-output-v1",
            allowed_principals=(command.actor_id, owner_id),
        )


async def database_clock(factory: async_sessionmaker[AsyncSession]) -> datetime:
    """Read trusted server time inside the I/O step; no host/client authorization clock."""
    async with factory() as session:
        value: datetime | None = await session.scalar(select(func.clock_timestamp()))
        if value is None or value.utcoffset() is None:
            raise ValueError("Database clock is unavailable")
        return value
