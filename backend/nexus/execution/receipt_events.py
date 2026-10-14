"""Trusted receipt-transaction event publisher; no provider or nested transaction."""

from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CompanyControl


class ReceiptEventPublisher(Protocol):
    """Server composition publishes ID-only outcome facts in the existing locked transaction."""

    async def publish(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        intent: EffectIntent,
        receipt: ActionReceipt,
        identity: VerifiedIdentity,
        now: datetime,
    ) -> None:
        """Derive native references without committing, granting or issuing an external call."""
        ...
