"""Genuine failed issued receipts create one ID-only wake alongside native outcome/cost facts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


class NativeReceiptEventPublisher:
    """Already-issued outcomes need native identity, never a fresh source execution grant."""

    def __init__(self, catalog: PlanAdmissionCatalog) -> None:
        self.catalog = PlanAdmissionCatalog.model_validate_json(catalog.model_dump_json())

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
        """Publish failed native receipt IDs; later reads retain independent privacy gates."""
        if receipt.outcome != "failed":
            return
        actual_work, actual_intent = await _stored_outcome(session, receipt)
        if intent is not actual_intent or work is not actual_work:
            raise ExecutionDeniedError("Receipt event needs actual session-owned native rows")
        resource_id = await self._resource(
            session, control, actual_work, actual_intent, receipt, identity
        )
        scope = BrainReadScope(
            company_id=work.company_id,
            workspace_id=work.workspace_id,
            principal_id=identity.principal_id,
            operation_id=receipt.receipt_id,
            trace_id=work.trace_id,
        )
        await append_event(
            session,
            scope,
            kind="receipt_recorded",
            resource_id=resource_id,
            deduplication_key=f"native.receipt.failed.v1:{receipt.action_id}:{canonical_sha256(receipt)}",
            now=now,
            action_id=receipt.action_id,
        )

    async def _resource(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        intent: EffectIntent,
        receipt: ActionReceipt,
        identity: VerifiedIdentity,
    ) -> UUID:
        """Use exact stored issuance/resource IDs; no private source bytes or reauthorization."""
        action = await session.get(JournalAction, receipt.action_id)
        if action is None:
            raise ExecutionDeniedError("Receipt event action is unavailable")
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        if (
            not session.in_transaction()
            or self.catalog.company_id != control.company_id
            or (control.company_id, work.company_id, identity.workspace_id, identity.principal_id)
            != (receipt.company_id, receipt.company_id, work.workspace_id, work.actor_id)
            or (action.company_id, action.task_id, action.trace_id, proposal.actor_id)
            != (work.company_id, work.task_id, work.trace_id, work.actor_id)
            or (intent.company_id, intent.task_id, intent.trace_id, intent.run_id, intent.action_id)
            != (work.company_id, work.task_id, work.trace_id, work.run_id, receipt.action_id)
            or (action.proposal_hash, intent.proposal_hash)
            != (receipt.proposal_hash, action_hash(proposal))
            or intent.state != "failed"
            or intent.receipt_json != receipt.model_dump_json()
        ):
            raise ExecutionDeniedError("Receipt event differs from actual issued outcome")
        target = next(
            (row.resource for row in self.catalog.resources if row.symbol == proposal.resource),
            None,
        )
        if (
            target is None
            or await session.get(BrainResource, (work.company_id, target.resource_id)) is None
        ):
            raise ExecutionDeniedError("Receipt event registered resource is unavailable")
        return target.resource_id


async def _stored_outcome(
    session: AsyncSession, receipt: ActionReceipt
) -> tuple[ExecutionWork, EffectIntent]:
    """Re-read actual persisted writes; a transient supplied ORM object cannot invent a wake."""
    actual_work = await session.scalar(
        select(ExecutionWork)
        .where(
            ExecutionWork.company_id == receipt.company_id,
            ExecutionWork.task_id == receipt.task_id,
        )
        .execution_options(populate_existing=True)
    )
    actual_intent = await session.scalar(
        select(EffectIntent)
        .where(
            EffectIntent.company_id == receipt.company_id,
            EffectIntent.action_id == receipt.action_id,
        )
        .execution_options(populate_existing=True)
    )
    if actual_work is None or actual_intent is None:
        raise ExecutionDeniedError("Receipt event stored outcome is unavailable")
    return actual_work, actual_intent
