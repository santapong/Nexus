"""Owner audit polls use actual saved dispatch/receipt identity, never a caller provider UUID."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.event_store import read_event
from nexus.company.contracts.results import ActionReceipt
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.draft_persistence import stored_draft
from nexus.company.notifications.draft_store import (
    NotificationDraftStore,
    owner_scope,
    require_draft_time,
)
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


async def known_message(
    session: AsyncSession, scope: CompanyControlScope, draft_id: UUID
) -> tuple[NotificationDispatchRow, ActionReceipt] | None:
    bound = await session.get(NotificationDispatchRow, (scope.company_id, draft_id))
    if bound is None:
        return None
    intent = await session.get(EffectIntent, (scope.company_id, bound.action_id))
    work = await session.get(ExecutionWork, (scope.company_id, bound.task_id))
    if (
        intent is None
        or work is None
        or (
            intent.task_id,
            intent.trace_id,
            intent.run_id,
            intent.intent_fence,
            intent.proposal_hash,
            intent.attempt_kind,
        )
        != (
            bound.task_id,
            bound.trace_id,
            bound.run_id,
            bound.intent_fence,
            bound.proposal_sha256,
            "tool_attempts",
        )
        or work.registration_hash != bound.registration_sha256
    ):
        raise NotificationUnavailableError("Native notification receipt binding is unavailable")
    if intent.receipt_json is None or intent.state != "succeeded":
        return None
    receipt = ActionReceipt.model_validate_json(intent.receipt_json)
    if receipt.outcome != "succeeded" or receipt.external_id is None:
        return None
    if (
        receipt.company_id,
        receipt.action_id,
        receipt.task_id,
        receipt.trace_id,
        receipt.proposal_hash,
    ) != (scope.company_id, bound.action_id, bound.task_id, bound.trace_id, bound.proposal_sha256):
        raise NotificationUnavailableError("Native notification receipt binding is unavailable")
    _provider_identity(receipt)
    return bound, receipt


async def current_owner_message(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    drafts: NotificationDraftStore,
    draft_id: UUID,
) -> NotificationDraft:
    row = await session.get(NotificationDraftRow, (scope.company_id, draft_id))
    if row is None:
        raise NotificationUnavailableError("Native notification draft is unavailable")
    draft = stored_draft(row)
    event = await read_event(session, scope.company_id, draft.signal.event_ids[0])
    if event is None:
        raise NotificationUnavailableError("Native notification event is unavailable")
    fact = await drafts.loader.load(session, control, owner_scope(scope, identity), identity, event)
    if fact.provenance != draft.provenance or fact.signal.state_sha256 != draft.signal.state_sha256:
        raise NotificationUnavailableError("Native notification source snapshot changed")
    drafts.recipients.require_current(draft.recipient_policy, await db_now(session))
    require_draft_time(draft, await db_now(session))
    return draft


def _provider_identity(receipt: ActionReceipt) -> None:
    assert receipt.external_id is not None
    try:
        UUID(receipt.external_id)
    except ValueError:
        raise NotificationUnavailableError(
            "Native notification provider identity is unavailable"
        ) from None
