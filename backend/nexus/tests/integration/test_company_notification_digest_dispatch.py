"""Actual native daily/weekly drafts consume managed M1 slots; mock provider only."""

from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_digest_fixture import configured_digest
from nexus.tests.notification_inbox_api_support import inbox_factory
from nexus.tests.notification_managed_execution import approved_sender, mock_dispatch

__all__ = ["inbox_factory"]


@pytest.mark.parametrize("kind", ["daily", "weekly"])
async def test_actual_managed_digest_retains_kind_and_one_permit_no_replay_post(
    inbox_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    kind: Literal["daily", "weekly"],
) -> None:
    _, cases = await configured_digest(inbox_factory, tmp_path, kind)
    case = cases[0]
    prepared, lease = await approved_sender(inbox_factory, case)
    calls: list[str] = []
    service = mock_dispatch(inbox_factory, case, calls)
    result = await service.dispatch(
        lease, identity(OWNER), case.selection.draft_id, prepared.action.proposal.action_id
    )
    assert result is not None and result.outcome == "accepted" and calls == ["POST"]
    async with runtime_transaction(inbox_factory, lease_scope(lease), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        slot = await session.get(
            NotificationDispatchRow, (lease.company_id, case.selection.draft_id)
        )
        assert slot is not None and slot.kind == kind
    assert (
        await service.dispatch(
            lease, identity(OWNER), case.selection.draft_id, prepared.action.proposal.action_id
        )
        is None
    )
    assert calls == ["POST"]
