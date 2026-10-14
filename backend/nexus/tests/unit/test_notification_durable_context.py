"""A sealed current context owns exactly the lease it must release on later failure."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nexus.execution import notification_worker_context as module
from nexus.execution.notification_dispatch_read import NotificationDispatchBinding
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.notification_durable_unit_fixture import recovery_inputs
from nexus.tests.unit.test_notification_durable_effect_worker import context


@pytest.mark.parametrize("mismatch", [False, True])
async def test_context_releases_exact_acquired_lease_on_final_denial_or_binding_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: bool
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    current = context(value)
    monkeypatch.setattr(
        module,
        "read_notification_dispatch",
        AsyncMock(
            return_value=NotificationDispatchBinding(
                current.command, current.binding, current.action, current.draft_id
            )
        ),
    )
    monkeypatch.setattr(
        type(value.services.reads.identities), "current", AsyncMock(return_value=current.credential)
    )
    lease = (
        current.lease.model_copy(update={"run_id": current.command.segment_id})
        if mismatch
        else current.lease
    )
    monkeypatch.setattr(module, "recover_notification_lease", AsyncMock(return_value=lease))
    monkeypatch.setattr(
        module,
        "require_current_credential",
        AsyncMock(
            side_effect=None if mismatch else ExecutionDeniedError("current membership denied")
        ),
    )
    with pytest.raises(ExecutionDeniedError):
        await module.prepare_notification_context(
            value.services, current.command, workflow_id=current.command.workflow_id
        )
    value.release.assert_awaited_once_with(lease, current.identity)


async def test_bare_signed_identity_dto_cannot_replace_process_sealed_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    current = context(value)
    monkeypatch.setattr(
        module,
        "read_notification_dispatch",
        AsyncMock(
            return_value=NotificationDispatchBinding(
                current.command, current.binding, current.action, current.draft_id
            )
        ),
    )
    monkeypatch.setattr(
        type(value.services.reads.identities), "current", AsyncMock(return_value=current.identity)
    )
    acquire = AsyncMock()
    monkeypatch.setattr(module, "recover_notification_lease", acquire)
    with pytest.raises(ExecutionDeniedError, match="sealed credential"):
        await module.prepare_notification_context(
            value.services, current.command, workflow_id=current.command.workflow_id
        )
    acquire.assert_not_awaited()
    value.release.assert_not_awaited()


async def test_reader_context_rejects_foreign_guard_reader_before_any_native_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.notifications.worker_config import FileNotificationWorkerRegistration
    from nexus.company.notifications.worker_guard import NotificationOperationGuard
    from nexus.execution.notification_worker_observation import read_notification_history

    value = await recovery_inputs(tmp_path, monkeypatch)
    guard = NotificationOperationGuard(
        value.guard.witness,
        value.guard.snapshot,
        FileNotificationWorkerRegistration(value.guard.reader._path),
    )
    with pytest.raises(ExecutionDeniedError):
        await read_notification_history(value.services, replace(context(value), guard=guard))
