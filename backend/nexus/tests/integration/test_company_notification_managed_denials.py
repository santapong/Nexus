"""Current native managed preparation denies unsupported owner-child/profile/source state."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.harness.journal_models import JournalAction
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.notification_managed_execution import configure_catalog, expiring_profile
from nexus.tests.notification_managed_fixture import configured_sender
from nexus.tests.notification_native_support import notifications_factory

__all__ = ["notifications_factory"]


@pytest.mark.parametrize(
    "failure", ["disabled", "non_owner_child", "stale_profile", "source_revoked"]
)
async def test_current_native_prepare_denies_without_any_pending_sender_action(
    notifications_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    case = await configured_sender(notifications_factory, tmp_path)
    selected, preparation = case.selection, case.preparation
    if failure == "disabled":
        preparation = ManagedNotificationPreparation(
            notifications_factory,
            case.drafts,
            case.plans.catalog,
            case.metric.store.artifacts,
            case.metric.store.freshness,
            policy=case.policy.model_copy(update={"enabled": False}),
        )
    elif failure == "non_owner_child":
        selected = selected.model_copy(
            update={"sender_task_id": case.metric.payload.children[0].binding.task_id}
        )
    elif failure == "stale_profile":
        preparation = configure_catalog(
            notifications_factory, case, expiring_profile(case, -1)
        ).preparation
    else:
        await owner_source(notifications_factory, active=False)
    with pytest.raises(ValueError):
        await preparation.prepare(control(), identity(OWNER), selected)
    async with management_owner_transaction(notifications_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JournalAction)
                .where(JournalAction.task_id == case.selection.sender_task_id)
            )
            == 0
        )
