"""Drain observations come from configured actual OS process handles, never caller flags/PIDs."""

import asyncio
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from nexus.company.management.base import ValueContract


class WorkerExit(ValueContract):
    pid: int = Field(gt=0)
    exit_code: int


class WorkerDrainWitness(ValueContract):
    company_id: UUID
    source_database: str
    scope: Literal["configured_owned_processes_exited"] = "configured_owned_processes_exited"
    observed_at: datetime
    workers: tuple[WorkerExit, ...] = Field(min_length=1, max_length=32)


class WorkerDrainProvider(Protocol):
    async def observe(self, company_id: UUID) -> WorkerDrainWitness: ...


class BackupKeyProvider(Protocol):
    async def key(self) -> bytes: ...


class OwnedWorkerDrain:
    """Operator supervisor registers handles at launch; this observer stops no unrelated process."""

    def __init__(
        self, company_id: UUID, database: str, workers: tuple[asyncio.subprocess.Process, ...]
    ) -> None:
        if not 1 <= len(workers) <= 32 or len({row.pid for row in workers}) != len(workers):
            raise ValueError("Backup registered worker inventory is unavailable")
        self.company_id, self.database, self.workers = company_id, database, workers

    async def observe(self, company_id: UUID) -> WorkerDrainWitness:
        if company_id != self.company_id or any(row.returncode is None for row in self.workers):
            raise ValueError("Backup registered workers are not drained")
        exits = tuple([WorkerExit(pid=row.pid, exit_code=await row.wait()) for row in self.workers])
        return WorkerDrainWitness(
            company_id=company_id,
            source_database=self.database,
            observed_at=datetime.now(UTC),
            workers=exits,
        )
