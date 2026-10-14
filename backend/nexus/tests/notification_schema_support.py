"""Exclusive normal014 restricted schema fixtures, never notification/business evidence."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.notifications.notification_models import NotificationDraftRow
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, migrate


@pytest.fixture
async def notification_schema_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_notification_schema"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
            await connection.execute(
                text("GRANT DELETE ON company_notification_drafts TO nexus_company_app")
            )
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


def draft_row(subject: UUID) -> NotificationDraftRow:
    """Schema placeholder JSON proves constraints only; never a native prepared draft."""
    return NotificationDraftRow(
        company_id=COMPANY,
        draft_id=uuid4(),
        kind="routine",
        subject_kind="work",
        subject_id=subject,
        native_state_sha256="a" * 64,
        trigger_sha256="b" * 64,
        recipient_class="owner",
        recipient_owner_id=OWNER,
        recipient_policy_id=uuid4(),
        recipient_policy_version="schema-only",
        recipient_policy_sha256="c" * 64,
        recipient_policy_json="{}",
        policy_version="schema-only",
        template_version="schema-only",
        payload_sha256="d" * 64,
        payload_json="{}",
        record_sha256="e" * 64,
        record_json="{}",
        due_bucket=None,
        scheduled_for=None,
        recorded_by=OWNER,
        operation_id=uuid4(),
        audit_trace_id=uuid4(),
        recorded_at=datetime.now(UTC),
    )


async def persist_schema_draft(
    factory: async_sessionmaker[AsyncSession], subject: UUID
) -> NotificationDraftRow:
    row = draft_row(subject)
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(row)
    return row
