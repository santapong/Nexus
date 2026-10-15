"""Factory and pre-request delegation only; no HTTP or provider operation is executed."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nexus.company.notifications.mixed_worker_dispatch import (
    MixedCredentialedResendTransport,
    MixedNotificationDispatcher,
)
from nexus.company.notifications.mixed_worker_intent import MixedCredentialNotificationIntentCheck
from nexus.company.notifications.worker_transport import CredentialedResendTransport
from nexus.tests.notification_rule_fixtures import declared_draft
from nexus.tests.unit.mixed_notification_fixture import mixed_case


def test_final_per_operation_dispatcher_preserves_concrete_factory(tmp_path: Path) -> None:
    case = mixed_case(tmp_path)
    first = MixedNotificationDispatcher(case.original, case.reads, case.guard)
    second = MixedNotificationDispatcher(case.original, case.reads, case.guard)
    assert first is not second
    check = first._intent_check(case.lease, case.guard.witness, case.draft_id, case.action_id)
    assert type(check) is MixedCredentialNotificationIntentCheck
    assert check.operation_guard is case.guard
    assert type(case.original)._intent_check is not type(first)._intent_check


async def test_inside_request_closes_full_check_before_any_transport_delegate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = mixed_case(tmp_path)
    case.check.draft = declared_draft()
    dispatcher = MixedNotificationDispatcher(case.original, case.reads, case.guard)
    transport = dispatcher._transport(case.check)
    assert type(transport) is MixedCredentialedResendTransport
    sent = AsyncMock(return_value=(200, b"{}"))
    monkeypatch.setattr(CredentialedResendTransport, "_request", sent)
    case.path.unlink()
    async with transport:
        with pytest.raises(ValueError):
            await transport._request("POST", "/emails")
    sent.assert_not_awaited()
