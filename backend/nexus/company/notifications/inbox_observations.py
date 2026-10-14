"""Bounded stored provider evidence is validated against native dispatch and M1 receipt."""

from __future__ import annotations

from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.dispatch_contracts import NotificationProviderObservation
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.inbox_contracts import (
    InboxUnavailableError,
    NotificationInboxEntry,
)
from nexus.company.notifications.observation_models import NotificationObservationRow
from nexus.company.notifications.observation_support import observation_row
from nexus.execution.effect_support import require_receipt_binding
from nexus.execution.runtime_models import EffectIntent, ExecutionWork


async def inbox_entry(session: AsyncSession, draft: NotificationDraft) -> NotificationInboxEntry:
    values = []
    for kind in ("submission", "delivery", "reconciliation"):
        row = await session.scalar(
            select(NotificationObservationRow)
            .where(
                NotificationObservationRow.company_id == draft.company_id,
                NotificationObservationRow.draft_id == draft.draft_id,
                NotificationObservationRow.observation_kind == kind,
            )
            .order_by(
                NotificationObservationRow.recorded_at.desc(),
                NotificationObservationRow.observation_id.desc(),
            )
            .limit(1)
        )
        value = await current_observation(session, draft, row) if row is not None else None
        values.append(value)
    return NotificationInboxEntry(
        company_id=draft.company_id,
        draft=draft,
        latest_submission=values[0],
        latest_delivery=values[1],
        latest_reconciliation=values[2],
    )


async def current_observation(
    session: AsyncSession, draft: NotificationDraft, row: NotificationObservationRow
) -> NotificationProviderObservation:
    try:
        value = NotificationProviderObservation.model_validate_json(row.record_json)
        expected = observation_row(value)
        if any(
            getattr(row, column.name) != getattr(expected, column.name)
            for column in cast(Table, NotificationObservationRow.__table__).columns
        ):
            raise ValueError("Native observation mirror differs")
        if (value.company_id, value.draft_id, value.payload_sha256) != (
            draft.company_id,
            draft.draft_id,
            draft.payload_sha256,
        ):
            raise ValueError("Native observation draft differs")
        receipt = await observation_receipt(session, draft, value)
        if (value.receipt_id, value.receipt_sha256) != (
            receipt.receipt_id,
            canonical_sha256(receipt),
        ):
            raise ValueError("Native observation receipt differs")
        result = value.status if value.status is not None else value.submission
        assert result is not None
        if result.provider_id is not None and receipt.external_id != str(result.provider_id):
            raise ValueError("Native observation provider differs")
        return value
    except ValueError:
        raise InboxUnavailableError("Notification unavailable") from None


async def observation_receipt(
    session: AsyncSession, draft: NotificationDraft, value: NotificationProviderObservation
) -> ActionReceipt:
    bound = await session.get(NotificationDispatchRow, (draft.company_id, draft.draft_id))
    if bound is None or (bound.action_id, bound.payload_sha256, bound.recipient_policy_sha256) != (
        value.action_id,
        draft.payload_sha256,
        draft.recipient_policy.sha256,
    ):
        raise ValueError("Native observation dispatch differs")
    intent = await session.get(EffectIntent, (draft.company_id, bound.action_id))
    work = await session.get(ExecutionWork, (draft.company_id, bound.task_id))
    if (
        intent is None
        or work is None
        or intent.receipt_json is None
        or (
            intent.task_id,
            intent.trace_id,
            intent.run_id,
            intent.intent_fence,
            intent.attempt_kind,
            intent.proposal_hash,
            work.registration_hash,
        )
        != (
            bound.task_id,
            bound.trace_id,
            bound.run_id,
            bound.intent_fence,
            "tool_attempts",
            bound.proposal_sha256,
            bound.registration_sha256,
        )
    ):
        raise ValueError("Native observation intent differs")
    receipt = ActionReceipt.model_validate_json(intent.receipt_json)
    require_receipt_binding(intent, receipt)
    if intent.state != receipt.outcome:
        raise ValueError("Native observation outcome differs")
    return receipt
