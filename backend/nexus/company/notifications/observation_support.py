"""Only actual native receipts bind safe immutable provider observation envelopes."""

from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.dispatch_contracts import NotificationProviderObservation
from nexus.company.notifications.observation_models import NotificationObservationRow


def observation_row(value: NotificationProviderObservation) -> NotificationObservationRow:
    result = value.status if value.status is not None else value.submission
    assert result is not None
    return NotificationObservationRow(
        company_id=value.company_id,
        observation_id=value.observation_id,
        draft_id=value.draft_id,
        action_id=value.action_id,
        payload_sha256=value.payload_sha256,
        observation_kind=value.kind,
        outcome=result.outcome,
        provider_id=result.provider_id,
        provider_event=value.status.provider_event if value.status else None,
        delivery_state=result.delivery_state,
        reason=result.reason,
        response_sha256=result.response_sha256,
        receipt_id=value.receipt_id,
        receipt_sha256=value.receipt_sha256,
        record_sha256=canonical_sha256(value),
        record_json=value.model_dump_json(by_alias=True),
        recorded_by=value.recorded_by,
        operation_id=value.operation_id,
        audit_trace_id=value.audit_trace_id,
        recorded_at=value.observed_at,
    )


async def append_observation(
    session: AsyncSession, value: NotificationProviderObservation
) -> NotificationProviderObservation:
    previous = await session.get(
        NotificationObservationRow, (value.company_id, value.observation_id)
    )
    if previous is not None:
        old = NotificationProviderObservation.model_validate_json(previous.record_json)
        if previous.record_sha256 != canonical_sha256(old) or old.model_dump(
            exclude={"observed_at", "operation_id", "audit_trace_id"}
        ) != value.model_dump(exclude={"observed_at", "operation_id", "audit_trace_id"}):
            raise ValueError("Provider observation replay differs from its native receipt")
        return old
    session.add(observation_row(value))
    await session.flush()
    return value


def observation_id(receipt: ActionReceipt, kind: str, response_sha256: str | None) -> UUID:
    return uuid5(receipt.action_id, f"notification:{kind}:{response_sha256 or 'unknown'}")
