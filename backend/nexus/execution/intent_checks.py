"""Trusted fast transaction checks; never serialized or accepted from user/model payloads."""

from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction


class BeforeIntentCheck(Protocol):
    """Server composition hook for current quote/catalog/evaluation consistency.

    Implementations may use this DB session for bounded validation. External
    provider/network I/O or user-supplied callables do not belong under the mutex.
    """

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        """Raise on stale or incompatible current state before any mutation or call permit."""
        ...


class CompositeBeforeIntentCheck:
    """Ordered trusted server checks sharing the caller's existing locked transaction."""

    def __init__(self, checks: tuple[BeforeIntentCheck, ...]) -> None:
        if not checks:
            raise ValueError("An intent-check composition requires at least one check")
        self._checks = checks

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        """Stop at the first rejection; never commit or start a nested transaction."""
        for check in self._checks:
            await check.validate(session, control, work, action, now)
