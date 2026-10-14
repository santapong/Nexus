"""Actual owner approval for additional initial-quota actions; no extra claim or topup."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.managed_contracts import PreparedNotification
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_managed_fixture import ManagedNotificationCase


async def approve_next(
    factory: async_sessionmaker[AsyncSession], case: ManagedNotificationCase
) -> PreparedNotification:
    prepared = await case.preparation.prepare(control(), identity(OWNER), case.selection)
    sender, action = prepared.sender, prepared.action.proposal
    scope = LedgerScope(
        company_id=sender.company_id,
        task_id=sender.task_id,
        trace_id=sender.trace_id,
        principal_id=OWNER,
    )
    journal = CompanyJournal(factory)
    await journal.approve_registered(
        scope, action.action_id, action_hash(action), datetime.now(UTC), identity=identity(OWNER)
    )
    await journal.authorize_registered(
        scope, action.action_id, datetime.now(UTC), (), identity=identity(OWNER)
    )
    return prepared
