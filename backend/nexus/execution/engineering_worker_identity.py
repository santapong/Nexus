"""Engineering retains the existing signature-verified process witness through effect clocks."""

from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


class EngineeringWorkerIdentities(Protocol):
    """Reuse the sealed verifier API without changing shared SchedulerIdentities."""

    async def current(self, expected_binding: RunBinding) -> AuthenticatedWorkerIdentity: ...


class EngineeringCredentialSourceGuard(BuilderSourceGuard):
    """Delegate complete protected source checks and retain credential time at real boundaries."""

    def __init__(
        self, original: BuilderSourceGuard, credential: AuthenticatedWorkerIdentity
    ) -> None:
        if (
            not isinstance(credential, AuthenticatedWorkerIdentity)
            or credential.identity != original.identity
        ):
            raise ValueError("Engineering authenticated credential witness unavailable")
        super().__init__(
            original.spec,
            original.policy,
            original.lease,
            original.identity,
            original.source,
            original.artifacts,
            original.freshness,
            original.catalog,
            containment=getattr(original, "containment", None),
        )
        self.credential = credential

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        await super().validate(session, control, work, action, now)
        self.credential.require_time(await db_now(session))

    def validate_time(self, now: datetime) -> None:
        """The inherited final source windows and sealed credential are checked together."""
        super().validate_time(now)
        self.credential.require_time(now)

    async def disclosure_windows(
        self, session: AsyncSession, control: CompanyControl
    ) -> tuple[datetime, ...]:
        windows = await super().disclosure_windows(session, control)
        self.credential.require_time(await db_now(session))
        return (*windows, self.credential.expires_at)
