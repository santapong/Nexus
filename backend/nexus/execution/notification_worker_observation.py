"""Current fenced body-free native notification history; no fresh permission or evidence writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.base import ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.dispatch_contracts import NotificationProviderObservation
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.observation_models import NotificationObservationRow
from nexus.company.notifications.observation_support import observation_row
from nexus.execution.effect_support import require_receipt_binding
from nexus.execution.notification_dispatch_read import (
    require_issued_binding,
    require_notification_command,
)
from nexus.execution.notification_worker_context import NotificationContext
from nexus.execution.notification_worker_contracts import NotificationSegmentResult
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    registration_digest,
    require_lease,
    runtime_transaction,
    snapshot,
)
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction

_DENIED = "Notification local history is unavailable"
NotificationHistoryStatus = Literal["submitted", "rejected", "outcome_unknown", "blocked"]


@dataclass(frozen=True, slots=True)
class NotificationNativeHistory:
    """Actual protected metadata was independently qualified; this object issues no permit."""

    intent_state: str | None
    receipt: ActionReceipt | None
    observation: NotificationProviderObservation | None
    observed_at: datetime


class NotificationDraftPins(ValueContract):
    """Selected immutable columns only; history reads never fetch private payload/record JSON."""

    payload_sha256: str
    recipient_policy_sha256: str
    kind: str


def notification_history_status(
    intent_state: str | None,
    receipt: ActionReceipt | None,
    observation: NotificationProviderObservation | None,
) -> tuple[NotificationHistoryStatus, tuple[str, ...]]:
    """Pure descriptive mapping only; caller must independently qualify actual native records."""
    # Cohesive classification table: collapsed FAILED and missing observations
    # must be considered alongside exact succeeded/unknown receipt mapping.
    if receipt is None:
        if observation is not None or intent_state in {"succeeded", "failed"}:
            raise ExecutionDeniedError(_DENIED)
        if intent_state in {"intent", "outcome_unknown"}:
            return "outcome_unknown", ("native_outcome_unresolved",)
        if intent_state is None:
            return "blocked", ("unissued_no_result",)
        raise ExecutionDeniedError(_DENIED)
    if intent_state != receipt.outcome:
        raise ExecutionDeniedError(_DENIED)
    if observation is not None:
        result = observation.submission
        if (
            result is None
            or observation.kind != "submission"
            or (
                observation.receipt_id != receipt.receipt_id
                or observation.receipt_sha256 != canonical_sha256(receipt)
                or observation.action_id != receipt.action_id
            )
        ):
            raise ExecutionDeniedError(_DENIED)
        expected = {
            "accepted": "succeeded",
            "rejected": "failed",
            "blocked": "failed",
            "unknown": "outcome_unknown",
        }[result.outcome]
        if receipt.outcome != expected:
            raise ExecutionDeniedError(_DENIED)
    if receipt.outcome == "succeeded":
        if receipt.external_id is None:
            raise ExecutionDeniedError(_DENIED)
        try:
            provider = UUID(receipt.external_id)
        except (ValueError, TypeError) as exc:
            raise ExecutionDeniedError(_DENIED) from exc
        if (
            observation is not None
            and observation.submission is not None
            and observation.submission.provider_id != provider
        ):
            raise ExecutionDeniedError(_DENIED)
        return "submitted", (() if observation is not None else ("submission_observation_missing",))
    if receipt.external_id is not None:
        raise ExecutionDeniedError(_DENIED)
    if receipt.outcome == "outcome_unknown":
        return "outcome_unknown", ("native_outcome_unresolved",)
    if (
        observation is not None
        and observation.submission is not None
        and observation.submission.outcome == "rejected"
    ):
        return "rejected", ()
    return "blocked", ("classification_unavailable",)


def require_observation_mirrors(
    row: NotificationObservationRow,
    value: NotificationProviderObservation,
) -> None:
    """Full immutable JSON/column mirrors must agree before descriptive status selection."""
    if row.record_sha256 != canonical_sha256(value):
        raise ExecutionDeniedError(_DENIED)
    expected = observation_row(value)
    names = (
        "company_id",
        "observation_id",
        "draft_id",
        "action_id",
        "payload_sha256",
        "observation_kind",
        "outcome",
        "provider_id",
        "provider_event",
        "delivery_state",
        "reason",
        "response_sha256",
        "receipt_id",
        "receipt_sha256",
        "record_sha256",
        "record_json",
        "recorded_by",
        "operation_id",
        "audit_trace_id",
        "recorded_at",
    )
    if any(getattr(row, name) != getattr(expected, name) for name in names):
        raise ExecutionDeniedError(_DENIED)


async def read_notification_history(
    services: NotificationDispatchWorkerServices,
    context: NotificationContext,
) -> NotificationNativeHistory:
    """Actual owner/member/fence and native mirror proof precede any history metadata output."""
    # Cohesive >50-line read-only boundary: original issued fence and every native
    # immutable binding share CC; final lease/credential clock follows all awaited reads.
    scope = lease_scope(context.lease)
    if (
        context.identity != context.credential.identity
        or context.guard.witness is not context.credential
    ):
        raise ExecutionDeniedError(_DENIED)
    if (
        context.guard.reader is not services.reads.registrations
        or context.binding != context.guard.registration.sender
    ):
        raise ExecutionDeniedError(_DENIED)
    context.guard.require_company(context.command.company_id)
    context.guard.require_identity(context.identity)
    context.command.require_scope(scope)
    async with runtime_transaction(
        services.reads.factory, scope, context.identity, allow_paused=True, allow_inactive=True
    ) as (session, control, _):
        work = await execution_row(session, scope)
        if control.owner_id != context.identity.principal_id or work.actor_id != control.owner_id:
            raise ExecutionDeniedError(_DENIED)
        require_lease(work, context.lease, await db_now(session))
        actual = await dispatched_binding(session, work, scope, context.command.segment_id)
        row = await session.get(JournalAction, context.command.action_id)
        if (
            row is None
            or actual != context.command
            or (row.company_id, row.task_id, row.trace_id)
            != (work.company_id, work.task_id, work.trace_id)
        ):
            raise ExecutionDeniedError(_DENIED)
        action = ActionProposal.model_validate_json(row.proposal_json)
        if (
            action != context.action
            or action_hash(action) != row.proposal_hash
            or registration_digest(snapshot(work).registration) != work.registration_hash
        ):
            raise ExecutionDeniedError(_DENIED)
        parameters = require_notification_command(
            context.binding, action, actual, services.dispatcher.resource_symbol
        )
        if parameters.draft_id != context.draft_id:
            raise ExecutionDeniedError(_DENIED)
        intent = await session.get(EffectIntent, (work.company_id, action.action_id))
        slot = await session.get(NotificationDispatchRow, (work.company_id, context.draft_id))
        receipt = None
        observation = None
        if (intent is None) != (slot is None):
            raise ExecutionDeniedError(_DENIED)
        if intent is not None and slot is not None:
            require_issued_binding(work, action, parameters, intent, slot)
            saved = (
                (
                    await session.execute(
                        select(
                            NotificationDraftRow.payload_sha256,
                            NotificationDraftRow.recipient_policy_sha256,
                            NotificationDraftRow.kind,
                        ).where(
                            NotificationDraftRow.company_id == work.company_id,
                            NotificationDraftRow.draft_id == context.draft_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if saved is None:
                raise ExecutionDeniedError(_DENIED)
            pins = NotificationDraftPins.model_validate(dict(saved))
            if (pins.payload_sha256, pins.recipient_policy_sha256, pins.kind) != (
                slot.payload_sha256,
                slot.recipient_policy_sha256,
                slot.kind,
            ):
                raise ExecutionDeniedError(_DENIED)
            if intent.receipt_json is not None:
                receipt = ActionReceipt.model_validate_json(intent.receipt_json)
                require_receipt_binding(intent, receipt)
            rows = tuple(
                (
                    await session.scalars(
                        select(NotificationObservationRow)
                        .where(
                            NotificationObservationRow.company_id == work.company_id,
                            NotificationObservationRow.draft_id == context.draft_id,
                            NotificationObservationRow.observation_kind == "submission",
                        )
                        .limit(2)
                    )
                ).all()
            )
            if len(rows) > 1:
                raise ExecutionDeniedError(_DENIED)
            if rows:
                observation = NotificationProviderObservation.model_validate_json(
                    rows[0].record_json
                )
                require_observation_mirrors(rows[0], observation)
                if (
                    observation.company_id,
                    observation.draft_id,
                    observation.action_id,
                    observation.payload_sha256,
                    observation.recorded_by,
                    observation.operation_id,
                    observation.audit_trace_id,
                ) != (
                    work.company_id,
                    context.draft_id,
                    action.action_id,
                    slot.payload_sha256,
                    slot.issued_by,
                    action.action_id,
                    work.trace_id,
                ):
                    raise ExecutionDeniedError(_DENIED)
            notification_history_status(intent.state, receipt, observation)
        final = await db_now(session)
        require_lease(work, context.lease, final)
        services.require_enabled()
        services.reads.require_registration(context.guard.snapshot)
        context.guard.require_identity(context.identity)
        context.guard.require_time(final)
        return NotificationNativeHistory(
            intent.state if intent else None, receipt, observation, final
        )


async def observe_notification_segment(
    services: NotificationDispatchWorkerServices,
    context: NotificationContext,
    *,
    failure_kind: str | None = None,
) -> NotificationSegmentResult:
    """Describe native outcome without downgrading a known receipt after an adapter exception."""
    actual = await read_notification_history(services, context)
    status, limitations = notification_history_status(
        actual.intent_state, actual.receipt, actual.observation
    )
    if failure_kind is not None:
        limitations = (*limitations, "operation_failed_after_admission")
    return NotificationSegmentResult(
        company_id=context.command.company_id,
        command=context.command,
        status=status,
        receipt_id=actual.receipt.receipt_id if actual.receipt else None,
        receipt_sha256=canonical_sha256(actual.receipt) if actual.receipt else None,
        observation_id=actual.observation.observation_id if actual.observation else None,
        observation_sha256=canonical_sha256(actual.observation) if actual.observation else None,
        observed_at=actual.observed_at,
        billing="unconfirmed",
        limitations=limitations,
    )
