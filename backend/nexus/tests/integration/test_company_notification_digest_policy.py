"""Actual approved managed digest cannot issue after current server policy disables its kind."""

from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_digest_fixture import configured_digest
from nexus.tests.notification_inbox_api_support import inbox_factory
from nexus.tests.notification_managed_execution import approved_sender, mock_dispatch

__all__ = ["inbox_factory"]


@pytest.mark.parametrize("kind", ["daily", "weekly"])
async def test_current_registered_digest_policy_flag_loss_never_inserts_native_intent(
    inbox_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    kind: Literal["daily", "weekly"],
) -> None:
    _, cases = await configured_digest(inbox_factory, tmp_path, kind)
    case = cases[0]
    prepared, lease = await approved_sender(inbox_factory, case)
    case.drafts.policy = case.drafts.policy.model_copy(update={f"{kind}_digest": False})
    calls: list[str] = []
    with pytest.raises(NotificationUnavailableError, match="digest window"):
        await mock_dispatch(inbox_factory, case, calls).dispatch(
            lease, identity(OWNER), case.selection.draft_id, prepared.action.proposal.action_id
        )
    assert calls == []
    async with runtime_transaction(inbox_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.get(EffectIntent, (lease.company_id, prepared.action.proposal.action_id))
            is None
        )
        assert (
            await session.get(NotificationDispatchRow, (lease.company_id, case.selection.draft_id))
            is None
        )
