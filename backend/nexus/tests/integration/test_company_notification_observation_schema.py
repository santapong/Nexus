"""Actual SQL NULL/delivery guards; placeholder JSON is not provider or business evidence."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.notification_models import NotificationObservationRow
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_intent_schema_support import SchemaBinding, authorized_schema_work
from nexus.tests.notification_schema_support import (
    notification_schema_factory as notification_schema_factory,
)
from nexus.tests.notification_schema_support import persist_schema_draft


def observation(draft_id: UUID, action_id: UUID) -> NotificationObservationRow:
    """Schema-only safe unknown submission; never a decoded actual Resend response."""
    return NotificationObservationRow(
        company_id=COMPANY,
        observation_id=uuid4(),
        draft_id=draft_id,
        action_id=action_id,
        payload_sha256="d" * 64,
        observation_kind="submission",
        outcome="unknown",
        provider_id=None,
        provider_event=None,
        delivery_state="unknown",
        reason="network_unknown",
        response_sha256=None,
        receipt_id=None,
        receipt_sha256=None,
        record_sha256="a" * 64,
        record_json="{}",
        recorded_by=OWNER,
        operation_id=uuid4(),
        audit_trace_id=uuid4(),
    )


@pytest.mark.parametrize(
    "failure",
    [
        "accepted_null",
        "delivered_submission",
        "sent_delivered",
        "provider_no_receipt",
        "response_null",
        "different_payload",
    ],
)
async def test_restricted_provider_null_and_delivery_shape_cannot_invent_evidence(
    notification_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    case, lease, action = await authorized_schema_work(notification_schema_factory, tmp_path)
    draft = await persist_schema_draft(notification_schema_factory, lease.task_id)
    await case.native.effects.begin(
        lease, identity(lease.actor_id), action, before_intent=SchemaBinding(draft)
    )
    row = observation(draft.draft_id, action)
    if failure == "accepted_null":
        row.outcome, row.reason = "accepted", "accepted"
    elif failure == "delivered_submission":
        row.delivery_state = "delivered"
    elif failure == "sent_delivered":
        row.observation_kind, row.outcome, row.reason = "delivery", "observed", "observed"
        row.provider_id, row.provider_event, row.delivery_state = uuid4(), "sent", "delivered"
        row.response_sha256, row.receipt_id, row.receipt_sha256 = "b" * 64, uuid4(), "c" * 64
    elif failure == "provider_no_receipt":
        row.outcome, row.reason, row.provider_id, row.response_sha256 = (
            "accepted",
            "accepted",
            uuid4(),
            "b" * 64,
        )
    elif failure == "response_null":
        row.outcome, row.reason, row.provider_id = "accepted", "accepted", uuid4()
        row.receipt_id, row.receipt_sha256 = uuid4(), "c" * 64
    else:
        row.payload_sha256 = "f" * 64
    with pytest.raises(DBAPIError):
        async with notification_schema_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            session.add(row)
            await session.flush()


async def test_unknown_submission_keeps_nullable_provider_and_initial_record_unique(
    notification_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case, lease, action = await authorized_schema_work(notification_schema_factory, tmp_path)
    draft = await persist_schema_draft(notification_schema_factory, lease.task_id)
    await case.native.effects.begin(
        lease, identity(lease.actor_id), action, before_intent=SchemaBinding(draft)
    )
    async with notification_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(observation(draft.draft_id, action))
    with pytest.raises(DBAPIError, match="uq_notification_initial_submission"):
        async with notification_schema_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            session.add(observation(draft.draft_id, action))
