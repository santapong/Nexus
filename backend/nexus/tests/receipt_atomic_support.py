"""Controlled real receipt-event transaction rejection and natural lease expiry."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.results import ActionReceipt
from nexus.company.notifications.receipt_event_publisher import NativeReceiptEventPublisher
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl
from nexus.tests.generated_artifact_fixture import GeneratedScenario


def failed_receipt(item: GeneratedScenario) -> ActionReceipt:
    """Exact issued failure fixture, not independent business execution evidence."""
    action = item.action
    return ActionReceipt(
        company_id=action.company_id,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        proposal_hash=action_hash(action),
        outcome="failed",
        recorded_at=datetime.now(UTC),
        artifacts=(),
    )


class ObservedReceiptPublisher(NativeReceiptEventPublisher):
    """Actual event append followed by controlled rejection or natural clock crossing."""

    seen = False
    delay_seconds = 0.0
    reject_after_append = False

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
        await super().publish(session, control, work, intent, receipt, identity, now)
        self.seen = True
        if self.reject_after_append:
            raise ExecutionDeniedError("Controlled failure after actual receipt event append")
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)


def managed_effects(
    factory: async_sessionmaker[AsyncSession],
    item: GeneratedScenario,
    publisher: NativeReceiptEventPublisher,
) -> EffectStore:
    return EffectStore(
        factory,
        management_catalog=item.plans.catalog,
        management_artifacts=item.artifacts,
        management_freshness=item.publisher.freshness,
        receipt_events=publisher,
    )
